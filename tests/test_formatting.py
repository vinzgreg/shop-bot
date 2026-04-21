"""Tests for bot.formatting — table rendering."""

import pytest
from zoneinfo import ZoneInfo

from bot.formatting import format_item_table, format_reminder_table


class TestFormatItemTable:
    def test_single_item_no_quantity(self):
        items = [{"id": 1, "name": "milk", "quantity": None, "quantity_unit": None}]
        result = format_item_table(items)
        assert "```" in result
        assert "milk" in result
        assert "1" in result
        # No Qty column when no quantities
        assert "Qty" not in result

    def test_single_item_with_quantity(self):
        items = [{"id": 1, "name": "apples", "quantity": 3, "quantity_unit": None}]
        result = format_item_table(items)
        assert "Qty" in result
        assert "3x" in result
        assert "apples" in result

    def test_item_with_unit(self):
        items = [{"id": 1, "name": "flour", "quantity": 500, "quantity_unit": "g"}]
        result = format_item_table(items)
        assert "500g" in result

    def test_multiple_items(self):
        items = [
            {"id": 1, "name": "milk", "quantity": 2, "quantity_unit": "l"},
            {"id": 2, "name": "bread", "quantity": 1, "quantity_unit": None},
        ]
        result = format_item_table(items)
        assert "milk" in result
        assert "bread" in result
        assert "2l" in result

    def test_mixed_quantity_and_none(self):
        items = [
            {"id": 1, "name": "milk", "quantity": None, "quantity_unit": None},
            {"id": 2, "name": "apples", "quantity": 3, "quantity_unit": None},
        ]
        result = format_item_table(items)
        # Should have Qty column because at least one item has quantity
        assert "Qty" in result


class TestFormatReminderTable:
    def test_single_reminder(self):
        reminders = [{
            "id": 1,
            "remind_at": "2026-05-01T05:30:00+00:00",
            "message": "buy cake",
        }]
        tz = ZoneInfo("Europe/Berlin")
        result = format_reminder_table(reminders, tz)
        assert "buy cake" in result
        assert "2026-05-01" in result
        assert "```" in result

    def test_utc_to_local_conversion(self):
        reminders = [{
            "id": 1,
            "remind_at": "2026-05-01T05:30:00+00:00",  # UTC
            "message": "test",
        }]
        tz = ZoneInfo("Europe/Berlin")
        result = format_reminder_table(reminders, tz)
        # Europe/Berlin is UTC+2 in summer (CEST)
        assert "07:30" in result
