"""
SQLite persistence layer.

Every public function opens its own connection, runs the operation, and
closes it — no shared connection state.  WAL mode and foreign-key enforcement
are enabled on every connection.
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path("/app/data/shop/shop.db")


# ── Connection helper ─────────────────────────────────────────────────────────

@contextmanager
def _connection(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection with WAL mode and foreign keys; commit or rollback on exit."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Schema ────────────────────────────────────────────────────────────────────

def init_db(db_path: Path = DB_PATH) -> None:
    """Create all tables if they do not yet exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Initialising database at %s", db_path)

    with _connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS shopping_items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT    NOT NULL,
                quantity      INTEGER,
                quantity_unit TEXT,
                inserted_at   TEXT    NOT NULL
            );

            -- Unfired reminders: fired = 0.  Fired reminders are kept for audit.
            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                remind_at   TEXT    NOT NULL,
                message     TEXT    NOT NULL,
                inserted_at TEXT    NOT NULL,
                fired       INTEGER NOT NULL DEFAULT 0
            );

            -- One row per user; replaced each time the user runs a new command.
            CREATE TABLE IF NOT EXISTS undo_state (
                user_handle  TEXT PRIMARY KEY NOT NULL,
                action_type  TEXT NOT NULL,
                action_data  TEXT NOT NULL,
                created_at   TEXT NOT NULL
            );

            -- Full audit trail of every incoming DM.
            CREATE TABLE IF NOT EXISTS interaction_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_handle TEXT    NOT NULL,
                raw_message TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL
            );

            -- Generic key/value store for small bits of bot state
            -- (e.g. last processed Mastodon notification id).
            CREATE TABLE IF NOT EXISTS kv (
                key   TEXT PRIMARY KEY NOT NULL,
                value TEXT NOT NULL
            );
        """)

    logger.debug("Database schema ready")


# ── Shopping list ─────────────────────────────────────────────────────────────

def add_item(
    name: str,
    quantity: Optional[int],
    quantity_unit: Optional[str],
    db_path: Path = DB_PATH,
) -> int:
    """
    Add an item.  If an item with the same name already exists (case-insensitive),
    increment its quantity by the given amount (or by 1) instead of creating a
    duplicate.  Returns the item id.
    """
    with _connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, quantity FROM shopping_items WHERE lower(name) = lower(?)",
            (name,),
        ).fetchone()

        if existing:
            increment = quantity or 1
            new_qty = (existing["quantity"] or 1) + increment
            conn.execute(
                "UPDATE shopping_items SET quantity = ? WHERE id = ?",
                (new_qty, existing["id"]),
            )
            logger.debug("Incremented '%s' quantity to %d", name, new_qty)
            return existing["id"]

        cur = conn.execute(
            "INSERT INTO shopping_items (name, quantity, quantity_unit, inserted_at)"
            " VALUES (?, ?, ?, ?)",
            (name, quantity, quantity_unit, _utc_now()),
        )
        logger.debug("Inserted new item '%s' qty=%s unit=%s", name, quantity, quantity_unit)
        return cur.lastrowid


def list_items(db_path: Path = DB_PATH) -> list[dict]:
    """Return all items ordered by insertion (oldest first)."""
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, quantity, quantity_unit FROM shopping_items ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def remove_item_by_number(number: int, db_path: Path = DB_PATH) -> Optional[dict]:
    """
    Remove the item at 1-based list position.
    Returns the deleted row as a dict, or None if the number is out of range.
    """
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, quantity, quantity_unit FROM shopping_items ORDER BY id"
        ).fetchall()
        if number < 1 or number > len(rows):
            return None
        target = dict(rows[number - 1])
        conn.execute("DELETE FROM shopping_items WHERE id = ?", (target["id"],))
    logger.debug("Removed item #%d '%s'", number, target["name"])
    return target


def remove_item_by_name(name: str, db_path: Path = DB_PATH) -> Optional[dict]:
    """
    Remove the first case-insensitive exact match by name.
    Returns the deleted row as a dict, or None if not found.
    """
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, name, quantity, quantity_unit FROM shopping_items"
            " WHERE lower(name) = lower(?) ORDER BY id LIMIT 1",
            (name,),
        ).fetchone()
        if not row:
            return None
        target = dict(row)
        conn.execute("DELETE FROM shopping_items WHERE id = ?", (target["id"],))
    logger.debug("Removed item '%s' by name", name)
    return target


def clear_items(db_path: Path = DB_PATH) -> list[dict]:
    """Delete every item from the shopping list. Returns all deleted rows."""
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, quantity, quantity_unit FROM shopping_items ORDER BY id"
        ).fetchall()
        conn.execute("DELETE FROM shopping_items")
    logger.debug("Cleared %d item(s) from shopping list", len(rows))
    return [dict(r) for r in rows]


def remove_items_by_ids(ids: list[int], db_path: Path = DB_PATH) -> list[dict]:
    """
    Remove multiple items by id in a single transaction.  Returns the rows
    that existed and were deleted; ids that no longer exist are ignored.
    """
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    params = tuple(ids)
    with _connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT id, name, quantity, quantity_unit FROM shopping_items"
            f" WHERE id IN ({placeholders})",
            params,
        ).fetchall()
        if rows:
            conn.execute(
                f"DELETE FROM shopping_items WHERE id IN ({placeholders})",
                params,
            )
    logger.debug("Removed %d item(s) by id", len(rows))
    return [dict(r) for r in rows]


def restore_item(
    name: str,
    quantity: Optional[int],
    quantity_unit: Optional[str],
    db_path: Path = DB_PATH,
) -> None:
    """Re-insert a previously removed item (used by undo)."""
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO shopping_items (name, quantity, quantity_unit, inserted_at)"
            " VALUES (?, ?, ?, ?)",
            (name, quantity, quantity_unit, _utc_now()),
        )
    logger.debug("Restored item '%s'", name)


def get_item_quantity(name: str, db_path: Path = DB_PATH) -> Optional[int]:
    """Return the current quantity of an item, or None if not found."""
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT quantity FROM shopping_items WHERE lower(name) = lower(?) LIMIT 1",
            (name,),
        ).fetchone()
    return row["quantity"] if row else None


def update_item_quantity(name: str, quantity: int, db_path: Path = DB_PATH) -> bool:
    """Set the quantity of the first matching item. Returns True if found."""
    with _connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE shopping_items SET quantity = ? WHERE lower(name) = lower(?)",
            (quantity, name),
        )
        updated = cur.rowcount > 0
    logger.debug("update_item_quantity '%s' → %d: found=%s", name, quantity, updated)
    return updated


# ── Reminders ─────────────────────────────────────────────────────────────────

def add_reminder(remind_at_utc: str, message: str, db_path: Path = DB_PATH) -> int:
    """Store a new reminder.  remind_at_utc must be a UTC ISO-8601 string."""
    with _connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO reminders (remind_at, message, inserted_at, fired)"
            " VALUES (?, ?, ?, 0)",
            (remind_at_utc, message, _utc_now()),
        )
        reminder_id = cur.lastrowid
    logger.debug("Added reminder id=%d at %s: '%s'", reminder_id, remind_at_utc, message)
    return reminder_id


def list_reminders(db_path: Path = DB_PATH) -> list[dict]:
    """Return all unfired reminders sorted by remind_at ascending."""
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, remind_at, message FROM reminders"
            " WHERE fired = 0 ORDER BY remind_at"
        ).fetchall()
    return [dict(r) for r in rows]


def delete_reminder_by_number(number: int, db_path: Path = DB_PATH) -> Optional[dict]:
    """
    Delete the reminder at 1-based sorted position.
    Returns the deleted row as a dict, or None if out of range.
    """
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, remind_at, message FROM reminders"
            " WHERE fired = 0 ORDER BY remind_at"
        ).fetchall()
        if number < 1 or number > len(rows):
            return None
        target = dict(rows[number - 1])
        conn.execute("DELETE FROM reminders WHERE id = ?", (target["id"],))
    logger.debug("Deleted reminder #%d (id=%d)", number, target["id"])
    return target


def delete_reminder_by_id(reminder_id: int, db_path: Path = DB_PATH) -> None:
    """Delete a reminder by its primary key (used by undo)."""
    with _connection(db_path) as conn:
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    logger.debug("Deleted reminder id=%d", reminder_id)


def delete_all_reminders(db_path: Path = DB_PATH) -> list[dict]:
    """Delete all unfired reminders. Returns list of all deleted rows."""
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, remind_at, message FROM reminders WHERE fired = 0"
        ).fetchall()
        deleted = [dict(r) for r in rows]
        conn.execute("DELETE FROM reminders WHERE fired = 0")
    logger.debug("Deleted all %d unfired reminders", len(deleted))
    return deleted


def restore_reminder(remind_at_utc: str, message: str, db_path: Path = DB_PATH) -> None:
    """Re-insert a deleted reminder (used by undo)."""
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO reminders (remind_at, message, inserted_at, fired)"
            " VALUES (?, ?, ?, 0)",
            (remind_at_utc, message, _utc_now()),
        )
    logger.debug("Restored reminder at %s", remind_at_utc)


def get_due_reminders(now_utc: str, db_path: Path = DB_PATH) -> list[dict]:
    """Return all unfired reminders whose remind_at is at or before now_utc."""
    with _connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, remind_at, message FROM reminders"
            " WHERE fired = 0 AND remind_at <= ?",
            (now_utc,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_fired(reminder_id: int, db_path: Path = DB_PATH) -> None:
    """Mark a reminder as fired so it is not sent again."""
    with _connection(db_path) as conn:
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
    logger.debug("Marked reminder id=%d as fired", reminder_id)


# ── Undo state ────────────────────────────────────────────────────────────────

def set_undo(
    user_handle: str,
    action_type: str,
    action_data: dict,
    db_path: Path = DB_PATH,
) -> None:
    """Store undo state for a user, replacing any previous undo entry."""
    with _connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO undo_state (user_handle, action_type, action_data, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_handle) DO UPDATE SET
                action_type = excluded.action_type,
                action_data = excluded.action_data,
                created_at  = excluded.created_at
            """,
            (user_handle, action_type, json.dumps(action_data), _utc_now()),
        )
    logger.debug("Stored undo state for %s: %s", user_handle, action_type)


def get_and_clear_undo(
    user_handle: str,
    db_path: Path = DB_PATH,
) -> Optional[tuple[str, dict]]:
    """
    Retrieve and delete the undo state for a user in one transaction.
    Returns (action_type, action_data) or None if no undo state exists.
    """
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT action_type, action_data FROM undo_state WHERE user_handle = ?",
            (user_handle,),
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM undo_state WHERE user_handle = ?", (user_handle,))
    return row["action_type"], json.loads(row["action_data"])


# ── Key/value state ───────────────────────────────────────────────────────────

def get_kv(key: str, db_path: Path = DB_PATH) -> Optional[str]:
    """Return the stored value for key, or None if not set."""
    with _connection(db_path) as conn:
        row = conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_kv(key: str, value: str, db_path: Path = DB_PATH) -> None:
    """Insert or replace the value for key."""
    with _connection(db_path) as conn:
        conn.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# ── Interaction log ───────────────────────────────────────────────────────────

def log_interaction(user_handle: str, raw_message: str, db_path: Path = DB_PATH) -> None:
    """Append an incoming DM to the audit log.  Failures are logged but not raised."""
    try:
        with _connection(db_path) as conn:
            conn.execute(
                "INSERT INTO interaction_log (user_handle, raw_message, timestamp)"
                " VALUES (?, ?, ?)",
                (user_handle, raw_message, _utc_now()),
            )
    except Exception:
        logger.exception("Failed to write interaction log for %s", user_handle)
