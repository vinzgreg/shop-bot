"""
Command handlers.

Each handler receives a ParsedCommand, the sender's account handle, the
Config, and the db_path.  It performs the requested operation and returns a
plain-text reply string.  Errors are caught and turned into user-friendly
messages so the bot never goes silent.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import database as db
from .config import Config
from .formatting import format_item_table, format_reminder_table
from .parser import ParsedCommand

logger = logging.getLogger(__name__)


# ── Dispatcher ────────────────────────────────────────────────────────────────

def handle(
    cmd: ParsedCommand,
    user_handle: str,
    config: Config,
    db_path=db.DB_PATH,
) -> str:
    """Dispatch a parsed command and return the reply text."""
    logger.info("Command '%s' from @%s", cmd.command, user_handle)

    _handlers = {
        "add":                 _add,
        "list":                _list,
        "remove":              _remove,
        "clear":               _clear,
        "update":              _update,
        "reminder_add":        _reminder_add,
        "reminder_list":       _reminder_list,
        "reminder_delete":     _reminder_delete,
        "reminder_delete_all": _reminder_delete_all,
        "undo":                _undo,
        "help":                _help,
        "unknown":             _unknown,
    }

    handler = _handlers.get(cmd.command, _unknown)
    try:
        return handler(cmd, user_handle, config, db_path)
    except Exception:
        logger.exception(
            "Unhandled error executing command '%s' for @%s", cmd.command, user_handle
        )
        return "Something went wrong. Please try again later."


# ── Individual handlers ───────────────────────────────────────────────────────

def _add(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    displays: list[str] = []
    for item in cmd.items:
        db.add_item(item.name, item.quantity, item.unit, db_path)
        displays.append(_item_display(item.name, item.quantity, item.unit))
        logger.info("@%s added '%s'", user_handle, item.name)

    db.set_undo(
        user_handle,
        "add",
        {"item_names": [item.name for item in cmd.items]},
        db_path,
    )

    if len(displays) == 1:
        return f"Added to list: {displays[0]}"
    return "Added to list:\n" + "\n".join(f"  - {d}" for d in displays)


def _list(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    items = db.list_items(db_path)
    if not items:
        return "The shopping list is empty."
    return format_item_table(items)


def _remove(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    # Resolve every target against a single snapshot of the list before any
    # deletion. Doing this up front prevents 1-based positions from shifting
    # as we delete, so "/remove 1, 2, 3" deletes the first three items.
    snapshot = db.list_items(db_path)
    resolved: list[dict] = []
    unresolved: list[str] = []
    seen_ids: set[int] = set()

    for target in cmd.remove_targets:
        item = _resolve_remove_target(target, snapshot, seen_ids)
        if item is None:
            unresolved.append(target)
        else:
            seen_ids.add(item["id"])
            resolved.append(item)

    if not resolved:
        if len(unresolved) == 1:
            return f"Item not found: {unresolved[0]}"
        return "No items found: " + ", ".join(unresolved)

    db.remove_items_by_ids([r["id"] for r in resolved], db_path)
    db.set_undo(user_handle, "remove", {"items": resolved}, db_path)

    logger.info(
        "@%s removed %d item(s): %s",
        user_handle, len(resolved), ", ".join(r["name"] for r in resolved),
    )

    displays = [
        _item_display(r["name"], r.get("quantity"), r.get("quantity_unit"))
        for r in resolved
    ]
    if len(displays) == 1:
        reply = f"Removed: {displays[0]}"
    else:
        reply = "Removed:\n" + "\n".join(f"  - {d}" for d in displays)
    if unresolved:
        reply += "\nNot found: " + ", ".join(unresolved)
    return reply


def _resolve_remove_target(
    target: str,
    snapshot: list[dict],
    seen_ids: set[int],
) -> Optional[dict]:
    """Resolve one /remove target to a snapshot row, or None if no match."""
    if target.isdigit():
        idx = int(target)
        if 1 <= idx <= len(snapshot):
            item = snapshot[idx - 1]
            if item["id"] not in seen_ids:
                return item
        return None

    return next(
        (
            item for item in snapshot
            if item["name"].lower() == target.lower() and item["id"] not in seen_ids
        ),
        None,
    )


def _clear(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    deleted = db.clear_items(db_path)
    if not deleted:
        return "The shopping list is already empty."

    db.set_undo(user_handle, "clear", {"items": deleted}, db_path)
    logger.info("@%s cleared %d item(s) from the list", user_handle, len(deleted))
    return f"Shopping list cleared ({len(deleted)} item(s) removed)."


def _update(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    old_qty = db.get_item_quantity(cmd.item_name, db_path)
    found = db.update_item_quantity(cmd.item_name, cmd.update_quantity, db_path)

    if not found:
        return f"Item not found: {cmd.item_name}"

    db.set_undo(
        user_handle,
        "update_quantity",
        {"item_name": cmd.item_name, "old_quantity": old_qty},
        db_path,
    )
    logger.info("@%s updated '%s' quantity to %d", user_handle, cmd.item_name, cmd.update_quantity)
    return f"Updated {cmd.item_name}: quantity is now {cmd.update_quantity}"


def _reminder_add(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    try:
        tz = ZoneInfo(config.bot.timezone)
    except ZoneInfoNotFoundError:
        logger.error("Unknown timezone in config: %s", config.bot.timezone)
        return f"Server misconfiguration: unknown timezone '{config.bot.timezone}'."

    time_str = cmd.reminder_time or config.bot.default_reminder_time

    try:
        local_dt = datetime.strptime(f"{cmd.reminder_date} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return (
            f"Invalid date or time: '{cmd.reminder_date} {time_str}'. "
            f"Use YYYY-MM-DD and HH:MM."
        )

    local_dt = local_dt.replace(tzinfo=tz)
    utc_str = local_dt.astimezone(timezone.utc).isoformat()

    reminder_id = db.add_reminder(utc_str, cmd.reminder_message, db_path)
    db.set_undo(user_handle, "reminder_add", {"reminder_id": reminder_id}, db_path)

    logger.info(
        "@%s added reminder at %s %s: '%s'",
        user_handle, cmd.reminder_date, time_str, cmd.reminder_message,
    )
    return f"Reminder set for {cmd.reminder_date} {time_str}: {cmd.reminder_message}"


def _reminder_list(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    reminders = db.list_reminders(db_path)
    if not reminders:
        return "No reminders scheduled."
    try:
        tz = ZoneInfo(config.bot.timezone)
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")
    return format_reminder_table(reminders, tz)


def _reminder_delete(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    deleted = db.delete_reminder_by_number(cmd.reminder_number, db_path)
    if not deleted:
        return f"Reminder #{cmd.reminder_number} not found."

    db.set_undo(user_handle, "reminder_delete", deleted, db_path)
    logger.info("@%s deleted reminder #%d", user_handle, cmd.reminder_number)
    return f"Deleted reminder #{cmd.reminder_number}: {deleted['message']}"


def _reminder_delete_all(
    cmd: ParsedCommand, user_handle: str, config: Config, db_path
) -> str:
    deleted = db.delete_all_reminders(db_path)
    if not deleted:
        return "No reminders to delete."

    db.set_undo(user_handle, "reminder_delete_all", {"reminders": deleted}, db_path)
    logger.info("@%s deleted all %d reminders", user_handle, len(deleted))
    return f"Deleted all {len(deleted)} reminder(s)."


def _undo(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    undo = db.get_and_clear_undo(user_handle, db_path)
    if undo is None:
        return "Nothing to undo."

    action_type, data = undo
    logger.info("@%s undoing '%s'", user_handle, action_type)

    if action_type == "add":
        names = data["item_names"]
        removed = [n for n in names if db.remove_item_by_name(n, db_path)]
        missing = [n for n in names if n not in removed]

        if len(names) == 1:
            if removed:
                return f"Undone: '{names[0]}' removed from the list."
            return f"Undo failed: '{names[0]}' is no longer on the list."

        parts = [f"Undone: removed {len(removed)} item(s) from the list."]
        if missing:
            parts.append(
                "Some were already gone: " + ", ".join(f"'{n}'" for n in missing)
            )
        return " ".join(parts)

    if action_type == "remove":
        items = data["items"]
        for it in items:
            db.restore_item(it["name"], it.get("quantity"), it.get("quantity_unit"), db_path)
        if len(items) == 1:
            return f"Undone: '{items[0]['name']}' restored to the list."
        return f"Undone: {len(items)} item(s) restored to the list."

    if action_type == "update_quantity":
        old = data["old_quantity"]
        db.update_item_quantity(data["item_name"], old or 1, db_path)
        return f"Undone: quantity of '{data['item_name']}' restored to {old}."

    if action_type == "reminder_add":
        db.delete_reminder_by_id(data["reminder_id"], db_path)
        return "Undone: reminder deleted."

    if action_type == "reminder_delete":
        db.restore_reminder(data["remind_at"], data["message"], db_path)
        return f"Undone: reminder restored — '{data['message']}'."

    if action_type == "clear":
        for it in data["items"]:
            db.restore_item(it["name"], it.get("quantity"), it.get("quantity_unit"), db_path)
        return f"Undone: {len(data['items'])} item(s) restored to the list."

    if action_type == "reminder_delete_all":
        for r in data["reminders"]:
            db.restore_reminder(r["remind_at"], r["message"], db_path)
        return f"Undone: {len(data['reminders'])} reminder(s) restored."

    logger.warning("Unknown undo action_type '%s' for @%s", action_type, user_handle)
    return "Undo not available for that action."


def _help(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    a = config.aliases
    default_time = config.bot.default_reminder_time
    return (
        "Shopping bot commands:\n"
        f"  @shop <item>[, <item>…]              — add one or more items to list\n"
        f"  @shop /list  (/{a.list})             — show shopping list\n"
        f"  @shop /remove <name|# [, …]|N-M>     — remove item(s)  (/{a.remove})\n"
        f"  @shop /delete [name|# [, …]|N-M]    — remove item(s), or clear whole list\n"
        f"  @shop /update <qty> <name>           — set item quantity\n"
        f"  @shop /reminder YYYY-MM-DD [HH:MM] <message>\n"
        f"                                       — add reminder (default time {default_time})\n"
        f"  @shop /reminder list                 — list reminders\n"
        f"  @shop /reminder delete <# or all>    — delete reminder(s)\n"
        f"  @shop /undo                          — undo last action\n"
        f"  @shop /help  (/{a.help})             — this message\n"
        f"\n"
        f"  German aliases: /{a.reminder}, /{a.list}, /{a.remove}, /{a.undo}, /{a.help}"
    )


def _unknown(cmd: ParsedCommand, user_handle: str, config: Config, db_path) -> str:
    return "I didn't understand that. Try /help for a list of commands."


# ── Formatting helper ─────────────────────────────────────────────────────────

def _item_display(name: str, quantity: Optional[int], unit: Optional[str]) -> str:
    if quantity and unit:
        return f"{quantity}{unit} {name}"
    if quantity:
        return f"{quantity}x {name}"
    return name
