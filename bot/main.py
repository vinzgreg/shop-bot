"""
Entry point.

Loads configuration, initialises the database, connects to Mastodon,
starts the reminder scheduler, and enters the DM-listening loop.
"""

import html
import html.parser
import logging
import re
import sys
from pathlib import Path

from .config import load_config, CONFIG_PATH
from .database import DB_PATH, init_db, log_interaction
from .handlers import handle
from .mastodon_client import MastodonClient
from .parser import parse
from .scheduler import start_scheduler

logger = logging.getLogger(__name__)


# ── HTML → plain text ─────────────────────────────────────────────────────────

class _HTMLStripper(html.parser.HTMLParser):
    """Collect text content while discarding all HTML tags."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts).strip()


def _strip_html(raw: str) -> str:
    """Convert Mastodon HTML content to plain text."""
    stripper = _HTMLStripper()
    stripper.feed(raw)
    text = stripper.get_text()
    # Decode HTML entities such as &amp; &lt; &gt;
    return html.unescape(text)


def _strip_mention(text: str, bot_acct: str) -> str:
    """
    Remove the leading @botname mention from the DM body.

    Mastodon may include the full handle (@shop@instance.social) or just the
    local part (@shop).  We strip whichever form is present.
    """
    local = bot_acct.split("@")[0]
    pattern = re.compile(
        rf"@{re.escape(local)}(?:@\S+)?\s*",
        re.IGNORECASE,
    )
    return pattern.sub("", text, count=1).strip()


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

    # ── DM callback ───────────────────────────────────────────────────────────
    def on_dm(status: dict) -> None:
        sender_acct = status["account"]["acct"]
        account_id  = status["account"]["id"]
        status_id   = status["id"]

        # Mastodon delivers content as HTML; convert to plain text first.
        raw_html = status.get("content", "")
        plain    = _strip_html(raw_html)

        logger.info("DM from @%s: %r", sender_acct, plain[:120])
        log_interaction(sender_acct, plain, DB_PATH)

        # Access control
        if not client.is_authorized(account_id):
            logger.info("Rejecting unauthorised user @%s", sender_acct)
            client.send_dm(
                status_id,
                sender_acct,
                "Sorry, you are not authorised to use this bot.",
            )
            return

        # Strip the @mention prefix, parse, execute, reply
        cleaned = _strip_mention(plain, client._bot_acct)
        cmd     = parse(cleaned, config.aliases)
        reply   = handle(cmd, sender_acct, config, DB_PATH)

        client.send_dm(status_id, sender_acct, reply)

    # ── Main loop ─────────────────────────────────────────────────────────────
    logger.info("Bot ready — listening for DMs")
    try:
        client.listen(on_dm)
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
