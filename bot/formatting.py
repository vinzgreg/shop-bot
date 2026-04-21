"""
Build the Unicode box-drawing tables sent back to users.

Wraps output in triple-backtick code blocks so monospace fonts render
correctly in Mastodon clients that support Markdown/CommonMark.
"""

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def format_item_table(items: list[dict]) -> str:
    """
    Render the shopping list as a fixed-width table.

    The Qty column is omitted entirely when no item has a quantity,
    keeping the output compact for simple lists.
    """
    rows = _build_item_rows(items)
    has_qty = any(r[1] for r in rows)

    if has_qty:
        lines = _render_three_col(rows, "No.", "Qty", "Item")
    else:
        # Drop the middle column
        two_col = [(r[0], r[2]) for r in rows]
        lines = _render_two_col(two_col, "No.", "Item")

    return _code_block(lines)


def format_reminder_table(reminders: list[dict], local_tz: ZoneInfo) -> str:
    """Render the reminder list as a fixed-width table in local time."""
    rows = []
    for i, rem in enumerate(reminders, start=1):
        utc_dt = _parse_utc(rem["remind_at"])
        local_str = utc_dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M")
        rows.append((str(i), local_str, rem["message"]))

    lines = _render_three_col(rows, "No.", "Date/Time", "Message")
    return _code_block(lines)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_item_rows(items: list[dict]) -> list[tuple[str, str, str]]:
    rows = []
    for i, item in enumerate(items, start=1):
        qty = item.get("quantity")
        unit = item.get("quantity_unit")
        if qty and unit:
            qty_str = f"{qty}{unit}"
        elif qty:
            qty_str = f"{qty}x"
        else:
            qty_str = ""
        rows.append((str(i), qty_str, item["name"]))
    return rows


def _render_two_col(rows: list[tuple[str, str]], h1: str, h2: str) -> list[str]:
    w1 = max(len(h1), max(len(r[0]) for r in rows))
    w2 = max(len(h2), max(len(r[1]) for r in rows))
    sep = "─" * (w1 + 1) + "┼" + "─" * (w2 + 1)
    lines = [f"{h1:>{w1}} │ {h2:<{w2}}", sep]
    for c1, c2 in rows:
        lines.append(f"{c1:>{w1}} │ {c2:<{w2}}")
    return lines


def _render_three_col(
    rows: list[tuple[str, str, str]], h1: str, h2: str, h3: str
) -> list[str]:
    w1 = max(len(h1), max(len(r[0]) for r in rows))
    w2 = max(len(h2), max(len(r[1]) for r in rows))
    w3 = max(len(h3), max(len(r[2]) for r in rows))
    sep = "─" * (w1 + 1) + "┼" + "─" * (w2 + 2) + "┼" + "─" * (w3 + 1)
    lines = [f"{h1:>{w1}} │ {h2:<{w2}} │ {h3:<{w3}}", sep]
    for c1, c2, c3 in rows:
        lines.append(f"{c1:>{w1}} │ {c2:<{w2}} │ {c3:<{w3}}")
    return lines


def _code_block(lines: list[str]) -> str:
    return "<pre>" + "\n".join(lines) + "</pre>"


def _parse_utc(iso_str: str) -> datetime:
    """Parse an ISO-8601 string and ensure it is timezone-aware (UTC)."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
