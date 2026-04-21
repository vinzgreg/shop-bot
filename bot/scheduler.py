"""
Reminder scheduler.

Runs a background thread that checks once per minute for reminders whose
fire time has passed, posts them as public toots, and marks them as fired.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from . import database as db

logger = logging.getLogger(__name__)


def start_scheduler(mastodon_client, db_path=db.DB_PATH) -> BackgroundScheduler:
    """
    Create, configure, and start the background scheduler.

    Returns the running scheduler so the caller can shut it down cleanly.
    """
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _fire_due_reminders,
        trigger="interval",
        minutes=1,
        args=[mastodon_client, db_path],
        id="fire_reminders",
        name="Fire due reminders",
        # Prevent overlapping runs if a previous execution stalls
        max_instances=1,
        # If the scheduler was offline and missed runs, fire once instead of many times
        coalesce=True,
    )
    scheduler.start()
    logger.info("Reminder scheduler started (interval: 1 minute)")
    return scheduler


def _fire_due_reminders(mastodon_client, db_path) -> None:
    """Check for due reminders and post each one as a public toot."""
    now_utc = datetime.now(timezone.utc).isoformat()

    try:
        due = db.get_due_reminders(now_utc, db_path)
    except Exception:
        logger.exception("Could not fetch due reminders from database")
        return

    if not due:
        logger.debug("No reminders due at %s", now_utc)
        return

    logger.info("%d reminder(s) due", len(due))

    for reminder in due:
        planned_by = reminder.get("planned_by")
        mention = f"@{planned_by} " if planned_by else ""
        message = f"{mention}Reminder: {reminder['message']}"
        try:
            mastodon_client.post_public(message)
            db.mark_reminder_fired(reminder["id"], db_path)
            logger.info("Fired reminder id=%d: '%s'", reminder["id"], reminder["message"])
        except Exception:
            # Log but keep going — we'll retry on the next tick because the
            # reminder is not marked as fired.
            logger.exception(
                "Failed to post reminder id=%d — will retry next minute", reminder["id"]
            )
