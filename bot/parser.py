"""
Parse raw DM text into a structured ParsedCommand.

The parser strips the leading slash commands, resolves language aliases, and
extracts structured fields (item name, quantity, date, etc.).  It never raises
— unknown or malformed input yields ParsedCommand(command="unknown").
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Matches an optional leading quantity+unit before the item name, e.g.:
#   "500g flour"  → qty=500  unit="g"   name="flour"
#   "2 apples"    → qty=2    unit=None  name="apples"
#   "apple"       → no match → name="apple"
_QUANTITY_PREFIX = re.compile(
    r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]+)?\s+(.+)$",
    re.DOTALL,
)

# Reminder date line: YYYY-MM-DD optionally followed by HH:MM then the message
_REMINDER_DATE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s+(.+)$",
    re.DOTALL,
)


@dataclass
class ParsedCommand:
    """Structured result of parsing one DM line."""

    command: str  # One of: add | list | remove | update | reminder_add |
                  #         reminder_list | reminder_delete | reminder_delete_all |
                  #         undo | help | unknown

    # --- add / update fields ---
    item_name: Optional[str] = None
    item_quantity: Optional[int] = None
    item_quantity_unit: Optional[str] = None

    # --- remove fields ---
    remove_target: Optional[str] = None    # numeric string or item name

    # --- update fields ---
    update_quantity: Optional[int] = None

    # --- reminder fields ---
    reminder_date: Optional[str] = None    # YYYY-MM-DD
    reminder_time: Optional[str] = None    # HH:MM  (None → use default)
    reminder_message: Optional[str] = None
    reminder_number: Optional[int] = None

    # --- debugging ---
    raw_text: str = field(default="", repr=False)


def parse(text: str, aliases) -> ParsedCommand:
    """
    Parse cleaned DM text (the @mention has already been stripped) into a
    ParsedCommand.  `aliases` is the AliasConfig instance from config.
    """
    text = text.strip()
    if not text:
        logger.debug("Empty message — returning unknown command")
        return ParsedCommand(command="unknown", raw_text=text)

    logger.debug("Parsing message: %r", text)

    # Normalise any alias to its English equivalent before dispatching.
    text = _resolve_aliases(text, aliases)
    lower = text.lower()

    if lower == "/list":
        return ParsedCommand(command="list", raw_text=text)

    if lower == "/help":
        return ParsedCommand(command="help", raw_text=text)

    if lower == "/undo":
        return ParsedCommand(command="undo", raw_text=text)

    if lower.startswith("/remove "):
        target = text[len("/remove "):].strip()
        return ParsedCommand(command="remove", remove_target=target, raw_text=text)

    if lower.startswith("/update "):
        return _parse_update(text)

    if lower.startswith("/reminder"):
        return _parse_reminder(text, aliases)

    # No command prefix → treat as an item to add to the shopping list.
    name, quantity, unit = _parse_item_text(text)
    return ParsedCommand(
        command="add",
        item_name=name,
        item_quantity=quantity,
        item_quantity_unit=unit,
        raw_text=text,
    )


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_aliases(text: str, aliases) -> str:
    """
    If the message starts with a known alias command, rewrite the leading
    keyword to its English equivalent.  Only the first token is compared so
    that e.g. '/erinnerung liste' rewrites to '/reminder liste'.
    """
    alias_map = {
        f"/{aliases.list.lower()}":     "/list",
        f"/{aliases.remove.lower()}":   "/remove",
        f"/{aliases.update.lower()}":   "/update",
        f"/{aliases.reminder.lower()}": "/reminder",
        f"/{aliases.undo.lower()}":     "/undo",
        f"/{aliases.help.lower()}":     "/help",
    }
    lower = text.lower()
    for alias, english in alias_map.items():
        if lower == alias or lower.startswith(alias + " "):
            tail = text[len(alias):]
            rewritten = english + tail
            if rewritten != text:
                logger.debug("Alias '%s' → '%s'", alias, english)
            return rewritten
    return text


def _parse_update(text: str) -> ParsedCommand:
    """Parse '/update <qty> <name>'."""
    rest = text[len("/update "):].strip()
    parts = rest.split(None, 1)
    if len(parts) == 2 and parts[0].isdigit():
        return ParsedCommand(
            command="update",
            update_quantity=int(parts[0]),
            item_name=parts[1].strip(),
            raw_text=text,
        )
    logger.debug("Could not parse /update arguments: %r", rest)
    return ParsedCommand(command="unknown", raw_text=text)


def _parse_reminder(text: str, aliases) -> ParsedCommand:
    """Parse all '/reminder …' sub-commands."""
    # Everything after '/reminder'
    rest = text[len("/reminder"):].strip()
    rest_lower = rest.lower()

    # /reminder list
    if rest_lower in ("list", aliases.reminder_list.lower()):
        return ParsedCommand(command="reminder_list", raw_text=text)

    # /reminder delete [N | all]
    delete_keywords = {"delete", aliases.reminder_delete.lower()}
    for kw in delete_keywords:
        if rest_lower == kw or rest_lower.startswith(kw + " "):
            after = rest[len(kw):].strip()
            all_keywords = {"all", aliases.reminder_all.lower()}
            if after.lower() in all_keywords:
                return ParsedCommand(command="reminder_delete_all", raw_text=text)
            if after.isdigit():
                return ParsedCommand(
                    command="reminder_delete",
                    reminder_number=int(after),
                    raw_text=text,
                )
            logger.debug("Invalid reminder delete target: %r", after)
            return ParsedCommand(command="unknown", raw_text=text)

    # /reminder YYYY-MM-DD [HH:MM] <message>
    m = _REMINDER_DATE.match(rest)
    if m:
        return ParsedCommand(
            command="reminder_add",
            reminder_date=m.group(1),
            reminder_time=m.group(2),      # None when no time was given
            reminder_message=m.group(3).strip(),
            raw_text=text,
        )

    logger.debug("Could not parse reminder arguments: %r", rest)
    return ParsedCommand(command="unknown", raw_text=text)


def _parse_item_text(text: str) -> tuple[str, Optional[int], Optional[str]]:
    """
    Extract (name, quantity, unit) from free text.

    Examples:
        "500g flour"  → ("flour", 500, "g")
        "2 apples"    → ("apples", 2, None)
        "apple"       → ("apple", None, None)
    """
    m = _QUANTITY_PREFIX.match(text)
    if m:
        qty_raw, unit, name = m.group(1), m.group(2), m.group(3).strip()
        try:
            # Convert float string to int (e.g. "1.5" → 1, "500" → 500)
            qty = int(float(qty_raw))
        except ValueError:
            qty = None
        # unit is None when the input was "2 apples" (no letter directly after digit)
        return name, qty, unit or None
    return text.strip(), None, None
