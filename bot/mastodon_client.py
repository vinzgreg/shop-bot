"""
Mastodon API wrapper.

Handles authentication, access-control checks, sending DMs, posting public
toots, and listening for incoming DMs via streaming (with a polling fallback).
"""

import logging
import time
from typing import Callable, Optional

from mastodon import (
    Mastodon,
    MastodonAPIError,
    MastodonNetworkError,
    StreamListener,
)

from .config import Config

logger = logging.getLogger(__name__)

# Seconds to wait between polling attempts when streaming is unavailable
_POLL_INTERVAL = 30

# Seconds to wait before retrying after an unexpected streaming error
_STREAM_RETRY_DELAY = 60

# Per-request API timeout in seconds
_API_TIMEOUT = 30


class _DMStreamListener(StreamListener):
    """Routes streaming notification events to the on_dm callback."""

    def __init__(self, on_dm: Callable, bot_acct: str):
        self._on_dm = on_dm
        self._bot_acct = bot_acct

    def on_notification(self, notification) -> None:
        if notification.get("type") != "mention":
            return
        status = notification.get("status", {})
        if status.get("visibility") != "direct":
            return
        sender = status["account"]["acct"]
        if sender == self._bot_acct:
            return  # never react to our own posts
        self._on_dm(status)

    def on_error(self, data) -> None:
        logger.error("Streaming error event received: %s", data)


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

    # ── Listening ──────────────────────────────────────────────────────────

    def listen(self, on_dm: Callable) -> None:
        """
        Block indefinitely and call on_dm(status) for every incoming DM.

        Tries the streaming API first.  Falls back to polling when streaming
        fails, and retries streaming periodically so we recover automatically
        when the instance becomes reachable again.
        """
        while True:
            try:
                logger.info("Starting streaming listener")
                listener = _DMStreamListener(on_dm, self._bot_acct)
                # stream_user blocks until the connection drops
                self._api.stream_user(listener)
                # If we reach here the stream ended cleanly — reconnect
                logger.warning("Streaming ended unexpectedly; reconnecting")
            except MastodonNetworkError:
                logger.warning(
                    "Streaming connection lost; switching to polling fallback"
                )
                self._poll_loop(on_dm)
            except Exception:
                logger.exception(
                    "Unexpected streaming error; retrying in %ds", _STREAM_RETRY_DELAY
                )
                time.sleep(_STREAM_RETRY_DELAY)

    def _poll_loop(self, on_dm: Callable) -> None:
        """
        Poll for new DM notifications.  Returns when streaming seems viable
        again so the caller can switch back.
        """
        last_seen_id = None
        consecutive_failures = 0

        while True:
            try:
                notifications = self._api.notifications(
                    types=["mention"],
                    since_id=last_seen_id,
                )
                consecutive_failures = 0

                # Process oldest first
                for notif in reversed(notifications):
                    status = notif.get("status", {})
                    if status.get("visibility") != "direct":
                        continue
                    sender = status["account"]["acct"]
                    if sender == self._bot_acct:
                        continue
                    on_dm(status)
                    last_seen_id = notif["id"]

                # After a successful poll, try to hand back to streaming
                logger.info("Poll succeeded — attempting to restore streaming")
                return

            except MastodonNetworkError:
                consecutive_failures += 1
                logger.warning(
                    "Poll attempt %d failed (network); retrying in %ds",
                    consecutive_failures,
                    _POLL_INTERVAL,
                )
            except Exception:
                consecutive_failures += 1
                logger.exception(
                    "Unexpected poll error (attempt %d); retrying in %ds",
                    consecutive_failures,
                    _POLL_INTERVAL,
                )

            time.sleep(_POLL_INTERVAL)
