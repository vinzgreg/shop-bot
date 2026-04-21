from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def format_item_table(items: list[dict]) -> str:
    lines = [f"Shopping list ({len(items)} item{'s' if len(items) != 1 else ''}):"]
    for i, item in enumerate(items, start=1):
        qty = item.get("quantity")
        unit = item.get("quantity_unit")
        if qty and unit:
            qty_str = f" {qty}{unit}"
        elif qty:
            qty_str = f" {qty}x"
        else:
            qty_str = ""
        lines.append(f"{i}.{qty_str} {item['name']}")
    return "\n".join(lines)


def format_reminder_table(reminders: list[dict], local_tz: ZoneInfo) -> str:
    lines = [f"Reminders ({len(reminders)}):"]
    for i, rem in enumerate(reminders, start=1):
        utc_dt = _parse_utc(rem["remind_at"])
        local_str = utc_dt.astimezone(local_tz).strftime("%Y-%m-%d %H:%M")
        planned_by = rem.get("planned_by")
        by_str = f" (by @{planned_by})" if planned_by else ""
        lines.append(f"{i}. {local_str} — {rem['message']}{by_str}")
    return "\n".join(lines)


def _parse_utc(iso_str: str) -> datetime:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
