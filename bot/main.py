"""
Entry point.

Loads configuration, initialises the database, connects to Mastodon,
starts the reminder scheduler, and enters the DM-listening loop.
"""

import logging
import sys
from pathlib import Path

from .config import load_config, CONFIG_PATH
from .database import DB_PATH, get_kv, init_db, log_interaction, set_kv
from .handlers import handle
from .mastodon_client import MastodonClient
from .parser import parse
from .scheduler import start_scheduler
from .text import strip_html, strip_mention

logger = logging.getLogger(__name__)

# kv key for the most recent Mastodon notification id we have processed.
# Used on startup to replay DMs received while the bot was offline.
LAST_NOTIFICATION_KEY = "last_seen_notification_id"


# ── Logging setup ─────────────────────────────────────────────────────────────

def _setup_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def run() -> None:
    # Config must be loaded before logging is set up so we know the log level.
    try:
        config = load_config(CONFIG_PATH)
    except (FileNotFoundError, PermissionError, ValueError) as exc:
        # Logging not yet configured — write directly to stderr.
        print(f"FATAL: Cannot load config: {exc}", file=sys.stderr)
        sys.exit(1)

    _setup_logging(config.bot.log_level)
    logger.info("Shop bot starting up")

    # Database
    try:
        init_db(DB_PATH)
    except Exception:
        logger.exception("Failed to initialise database at %s", DB_PATH)
        sys.exit(1)

    # Mastodon connection
    client = MastodonClient(config)
    try:
        client.connect()
    except Exception:
        logger.exception("Failed to connect to Mastodon at %s", config.mastodon.instance_url)
        sys.exit(1)

    # Reminder scheduler (background thread)
    scheduler = start_scheduler(client, DB_PATH)

    # ── Mention callback (DMs and public posts) ───────────────────────────────
    def on_dm(notification_id: str, status: dict) -> None:
        sender_acct = status["account"]["acct"]
        account_id  = status["account"]["id"]
        status_id   = status["id"]
        visibility  = status.get("visibility", "direct")

        # Mastodon delivers content as HTML; convert to plain text first.
        raw_html = status.get("content", "")
        plain    = strip_html(raw_html)

        logger.info("Mention (visibility=%s) from @%s: %r", visibility, sender_acct, plain[:120])
        log_interaction(sender_acct, plain, DB_PATH)

        def send_reply(text: str) -> None:
            if visibility == "direct":
                client.send_dm(status_id, sender_acct, text)
            else:
                client.send_public_reply(status_id, sender_acct, text)

        try:
            # Access control
            if not client.is_authorized(account_id):
                logger.info("Rejecting unauthorised user @%s", sender_acct)
                send_reply("Sorry, you are not authorised to use this bot.")
                return

            # Strip the @mention prefix, parse, execute, reply
            cleaned = strip_mention(plain, client._bot_acct)
            cmd     = parse(cleaned, config.aliases)
            reply   = handle(cmd, sender_acct, config, DB_PATH)

            send_reply(reply)
        finally:
            # Persist the high-water mark even if handling raised, so a
            # broken message can't permanently block backfill on restart.
            set_kv(LAST_NOTIFICATION_KEY, str(notification_id), DB_PATH)

    # ── Backfill missed DMs ───────────────────────────────────────────────────
    last_seen = get_kv(LAST_NOTIFICATION_KEY, DB_PATH)
    if last_seen is None:
        # First-ever start: don't replay all historical mentions. Record the
        # current head so subsequent restarts can backfill from this point.
        try:
            head = client.latest_notification_id()
        except Exception:
            logger.exception("Could not fetch initial notification head — skipping")
            head = None
        if head is not None:
            set_kv(LAST_NOTIFICATION_KEY, str(head), DB_PATH)
            logger.info("First run — recorded notification head id=%s", head)
    else:
        logger.info("Replaying DMs received since notification id=%s", last_seen)
        replayed = 0
        try:
            for nid, status in client.iter_dms_since(last_seen):
                on_dm(nid, status)
                replayed += 1
        except Exception:
            logger.exception("Backfill aborted after %d message(s)", replayed)
        else:
            logger.info("Backfill complete — replayed %d DM(s)", replayed)

    # ── Main loop ─────────────────────────────────────────────────────────────
    logger.info("Bot ready — listening for mentions")
    try:
        client.listen(
            on_dm,
            get_last_seen_id=lambda: get_kv(LAST_NOTIFICATION_KEY, DB_PATH),
        )
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — shutting down")
    except Exception:
        logger.exception("Fatal error in listener loop")
    finally:
        logger.info("Stopping scheduler")
        scheduler.shutdown(wait=False)
        logger.info("Bot stopped")


if __name__ == "__main__":
    run()
