"""
Mastodon API wrapper.

Handles authentication, access-control checks, sending DMs, posting public
toots, and listening for incoming DMs via streaming (with a polling fallback).
"""

import logging
import time
from typing import Callable, Iterator, Optional

from mastodon import (
    Mastodon,
    MastodonAPIError,
    MastodonNetworkError,
    StreamListener,
)
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout, Timeout

from .config import Config

logger = logging.getLogger(__name__)

# Seconds to wait between polling attempts when streaming is unavailable
_POLL_INTERVAL = 30

# Seconds to wait before retrying after an unexpected streaming error
_STREAM_RETRY_DELAY = 60

# Number of successful poll cycles before attempting to restore streaming
_POLL_CYCLES_BEFORE_STREAMING = 10

# Consecutive poll failures before logging an instance-connectivity error
_POLL_FAILURE_THRESHOLD = 3

# Per-request API timeout in seconds
_API_TIMEOUT = 30


def _is_dm_for_us(notification: dict, bot_acct: str) -> bool:
    """True iff this notification is a direct mention from someone other than us."""
    if notification.get("type") != "mention":
        return False
    status = notification.get("status") or {}
    if status.get("visibility") != "direct":
        return False
    sender = status.get("account", {}).get("acct")
    return sender is not None and sender != bot_acct


class _DMStreamListener(StreamListener):
    """Routes streaming notification events to the on_dm callback."""

    def __init__(self, on_dm: Callable, bot_acct: str):
        self._on_dm = on_dm
        self._bot_acct = bot_acct

    def on_notification(self, notification) -> None:
        logger.debug(
            "stream notification type=%s visibility=%s from=%s",
            notification.get("type"),
            (notification.get("status") or {}).get("visibility"),
            (notification.get("status") or {}).get("account", {}).get("acct"),
        )
        if not _is_dm_for_us(notification, self._bot_acct):
            return
        self._on_dm(notification["id"], notification["status"])

    def on_error(self, data) -> None:
        logger.error("Streaming error event received: %s", data)

    def handle_heartbeat(self) -> None:
        logger.debug("stream heartbeat")

    def on_unknown_event(self, name, unknown_event=None) -> None:
        logger.info("stream event %s: %r", name, unknown_event)


class MastodonClient:
    """Thin, resilient wrapper around Mastodon.py for the shopping bot."""

    def __init__(self, config: Config):
        self._config = config
        self._api: Optional[Mastodon] = None
        self._bot_acct: Optional[str] = None   # e.g. "shop@mastodon.social"

    # ── Setup ──────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Authenticate against the configured Mastodon instance."""
        logger.info("Connecting to %s", self._config.mastodon.instance_url)
        self._api = Mastodon(
            access_token=self._config.mastodon.access_token,
            api_base_url=self._config.mastodon.instance_url,
            request_timeout=_API_TIMEOUT,
        )
        me = self._api.me()
        self._bot_acct = me["acct"]
        logger.info("Authenticated as @%s", self._bot_acct)

    # ── Access control ─────────────────────────────────────────────────────

    def is_authorized(self, account_id: int) -> bool:
        """
        Return True if the given account is allowed to use the bot.

        "everyone"       — any account is accepted.
        "followers_only" — only accounts that follow the bot are accepted.
        """
        access = self._config.bot.access

        if access == "everyone":
            return True

        if access == "followers_only":
            try:
                relationships = self._api.account_relationships([account_id])
                if relationships and relationships[0].get("followed_by"):
                    return True
                logger.debug("Account id=%d is not a follower — rejected", account_id)
                return False
            except Exception:
                logger.exception(
                    "Could not verify follower status for account id=%d — defaulting to deny",
                    account_id,
                )
                return False

        logger.warning("Unknown access setting '%s' — defaulting to deny", access)
        return False

    # ── Posting ────────────────────────────────────────────────────────────

    def send_dm(self, reply_to_id: int, recipient_acct: str, text: str) -> None:
        """Reply to a DM.  Failures are logged but not raised."""
        content = f"@{recipient_acct} {text}"
        try:
            self._api.status_post(
                content,
                in_reply_to_id=reply_to_id,
                visibility="direct",
            )
            logger.debug("DM sent to @%s", recipient_acct)
        except (MastodonNetworkError, MastodonAPIError):
            logger.exception("Failed to send DM to @%s", recipient_acct)

    def post_public(self, text: str) -> None:
        """
        Post a public toot.  Raises on failure so the scheduler can decide
        whether to retry.
        """
        self._api.status_post(text, visibility="public")
        logger.debug("Public toot posted: %r", text[:80])

    # ── Backfill ───────────────────────────────────────────────────────────

    def latest_notification_id(self) -> Optional[str]:
        """Return the id of the most recent mention notification, or None."""
        recent = self._api.notifications(types=["mention"], limit=1)
        return recent[0]["id"] if recent else None

    def iter_dms_since(self, since_id: str) -> Iterator[tuple[str, dict]]:
        """
        Yield (notification_id, status) for every DM newer than since_id,
        oldest first.  Used to replay messages received while disconnected.
        """
        page = self._api.notifications(types=["mention"], since_id=since_id)
        notifs = self._api.fetch_remaining(page) if page else []
        # Mastodon returns newest-first; dispatch oldest-first.
        for n in reversed(notifs):
            if not _is_dm_for_us(n, self._bot_acct):
                continue
            yield n["id"], n["status"]

    # ── Listening ──────────────────────────────────────────────────────────

    def listen(self, on_dm: Callable, get_last_seen_id: Optional[Callable] = None) -> None:
        """
        Block indefinitely and call on_dm(status) for every incoming DM.

        Tries the streaming API first.  Falls back to polling when streaming
        fails, and retries streaming periodically so we recover automatically
        when the instance becomes reachable again.

        get_last_seen_id, if provided, is called each time we enter the poll
        fallback to seed since_id so already-processed notifications are not
        replayed.
        """
        while True:
            try:
                logger.info("Starting streaming listener")
                listener = _DMStreamListener(on_dm, self._bot_acct)
                # stream_user blocks until the connection drops
                self._api.stream_user(listener)
                # If we reach here the stream ended cleanly — reconnect
                logger.warning("Streaming ended unexpectedly; reconnecting")
            except (MastodonNetworkError, ReadTimeout, Timeout,
                    RequestsConnectionError, OSError):
                logger.warning(
                    "Streaming connection lost; switching to polling fallback"
                )
                initial = get_last_seen_id() if get_last_seen_id else None
                self._poll_loop(on_dm, initial_since_id=initial)
            except Exception:
                logger.exception(
                    "Unexpected streaming error; retrying in %ds", _STREAM_RETRY_DELAY
                )
                time.sleep(_STREAM_RETRY_DELAY)

    def _poll_loop(self, on_dm: Callable, initial_since_id: Optional[str] = None) -> None:
        """
        Poll for new DM notifications.  Returns after several consecutive
        successful polls so the caller can attempt to restore streaming.
        """
        last_seen_id = initial_since_id
        consecutive_failures = 0
        consecutive_successes = 0

        while True:
            try:
                notifications = self._api.notifications(
                    types=["mention"],
                    since_id=last_seen_id,
                )
                consecutive_failures = 0
                consecutive_successes += 1

                # Process oldest first
                for notif in reversed(notifications):
                    if not _is_dm_for_us(notif, self._bot_acct):
                        continue
                    on_dm(notif["id"], notif["status"])
                    last_seen_id = notif["id"]

                if consecutive_successes >= _POLL_CYCLES_BEFORE_STREAMING:
                    logger.info(
                        "Polling stable for %d cycles — attempting to restore streaming",
                        consecutive_successes,
                    )
                    return

            except MastodonNetworkError:
                consecutive_failures += 1
                consecutive_successes = 0
                if consecutive_failures == _POLL_FAILURE_THRESHOLD:
                    logger.error(
                        "Cannot reach Mastodon instance — streaming and %d "
                        "consecutive poll attempts failed. Instance may be down.",
                        consecutive_failures,
                    )
                elif consecutive_failures < _POLL_FAILURE_THRESHOLD:
                    logger.warning(
                        "Poll attempt %d failed (network); retrying in %ds",
                        consecutive_failures,
                        _POLL_INTERVAL,
                    )
                # After the threshold, stay quiet to avoid log spam — the
                # error has already been flagged.
            except Exception:
                consecutive_failures += 1
                consecutive_successes = 0
                if consecutive_failures == _POLL_FAILURE_THRESHOLD:
                    logger.error(
                        "Cannot reach Mastodon instance — streaming and %d "
                        "consecutive poll attempts failed. Instance may be down.",
                        consecutive_failures,
                    )
                else:
                    logger.exception(
                        "Unexpected poll error (attempt %d); retrying in %ds",
                        consecutive_failures,
                        _POLL_INTERVAL,
                    )

            time.sleep(_POLL_INTERVAL)
