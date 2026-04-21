"""Tests for bot.parser — command parsing logic."""

import pytest

from bot.parser import parse, _parse_item_text, ParsedCommand


class TestParseEmpty:
    def test_empty_string(self, aliases):
        cmd = parse("", aliases)
        assert cmd.command == "unknown"

    def test_whitespace_only(self, aliases):
        cmd = parse("   ", aliases)
        assert cmd.command == "unknown"


class TestParseAdd:
    def test_plain_item(self, aliases):
        cmd = parse("milk", aliases)
        assert cmd.command == "add"
        assert cmd.item_name == "milk"
        assert cmd.item_quantity is None
        assert cmd.item_quantity_unit is None

    def test_quantity_and_item(self, aliases):
        cmd = parse("2 apples", aliases)
        assert cmd.command == "add"
        assert cmd.item_name == "apples"
        assert cmd.item_quantity == 2
        assert cmd.item_quantity_unit is None

    def test_quantity_with_unit(self, aliases):
        cmd = parse("500g flour", aliases)
        assert cmd.command == "add"
        assert cmd.item_name == "flour"
        assert cmd.item_quantity == 500
        assert cmd.item_quantity_unit == "g"

    def test_quantity_with_unit_kg(self, aliases):
        cmd = parse("2kg potatoes", aliases)
        assert cmd.command == "add"
        assert cmd.item_name == "potatoes"
        assert cmd.item_quantity == 2
        assert cmd.item_quantity_unit == "kg"

    def test_float_quantity_truncates(self, aliases):
        cmd = parse("1.5l milk", aliases)
        assert cmd.command == "add"
        assert cmd.item_name == "milk"
        assert cmd.item_quantity == 1  # int(float("1.5")) = 1
        assert cmd.item_quantity_unit == "l"

    def test_multiword_item(self, aliases):
        cmd = parse("brown sugar", aliases)
        assert cmd.command == "add"
        assert cmd.item_name == "brown sugar"


class TestParseList:
    def test_list_command(self, aliases):
        cmd = parse("/list", aliases)
        assert cmd.command == "list"

    def test_list_case_insensitive(self, aliases):
        cmd = parse("/LIST", aliases)
        assert cmd.command == "list"


class TestParseRemove:
    def test_remove_by_number(self, aliases):
        cmd = parse("/remove 3", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_target == "3"

    def test_remove_by_name(self, aliases):
        cmd = parse("/remove milk", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_target == "milk"


class TestParseUpdate:
    def test_update_valid(self, aliases):
        cmd = parse("/update 5 apples", aliases)
        assert cmd.command == "update"
        assert cmd.update_quantity == 5
        assert cmd.item_name == "apples"

    def test_update_missing_quantity(self, aliases):
        cmd = parse("/update apples", aliases)
        assert cmd.command == "unknown"

    def test_update_non_numeric_quantity(self, aliases):
        cmd = parse("/update abc apples", aliases)
        assert cmd.command == "unknown"


class TestParseReminder:
    def test_reminder_add_date_and_time(self, aliases):
        cmd = parse("/reminder 2026-05-01 14:30 buy cake", aliases)
        assert cmd.command == "reminder_add"
        assert cmd.reminder_date == "2026-05-01"
        assert cmd.reminder_time == "14:30"
        assert cmd.reminder_message == "buy cake"

    def test_reminder_add_date_only(self, aliases):
        cmd = parse("/reminder 2026-05-01 buy cake", aliases)
        assert cmd.command == "reminder_add"
        assert cmd.reminder_date == "2026-05-01"
        assert cmd.reminder_time is None
        assert cmd.reminder_message == "buy cake"

    def test_reminder_list(self, aliases):
        cmd = parse("/reminder list", aliases)
        assert cmd.command == "reminder_list"

    def test_reminder_delete_number(self, aliases):
        cmd = parse("/reminder delete 2", aliases)
        assert cmd.command == "reminder_delete"
        assert cmd.reminder_number == 2

    def test_reminder_delete_all(self, aliases):
        cmd = parse("/reminder delete all", aliases)
        assert cmd.command == "reminder_delete_all"

    def test_reminder_invalid(self, aliases):
        cmd = parse("/reminder nonsense", aliases)
        assert cmd.command == "unknown"


class TestParseUndo:
    def test_undo(self, aliases):
        cmd = parse("/undo", aliases)
        assert cmd.command == "undo"


class TestParseHelp:
    def test_help(self, aliases):
        cmd = parse("/help", aliases)
        assert cmd.command == "help"


class TestAliases:
    def test_german_list(self, aliases):
        cmd = parse("/liste", aliases)
        assert cmd.command == "list"

    def test_german_remove(self, aliases):
        cmd = parse("/streiche milk", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_target == "milk"

    def test_german_help(self, aliases):
        cmd = parse("/hilfe", aliases)
        assert cmd.command == "help"

    def test_german_reminder(self, aliases):
        cmd = parse("/erinnerung liste", aliases)
        assert cmd.command == "reminder_list"

    def test_german_reminder_delete(self, aliases):
        cmd = parse("/erinnerung loesche 1", aliases)
        assert cmd.command == "reminder_delete"
        assert cmd.reminder_number == 1

    def test_german_reminder_delete_all(self, aliases):
        cmd = parse("/erinnerung loesche alle", aliases)
        assert cmd.command == "reminder_delete_all"


class TestParseItemText:
    def test_plain_name(self):
        name, qty, unit = _parse_item_text("bread")
        assert name == "bread"
        assert qty is None
        assert unit is None

    def test_quantity_no_unit(self):
        name, qty, unit = _parse_item_text("3 eggs")
        assert name == "eggs"
        assert qty == 3
        assert unit is None

    def test_quantity_with_unit(self):
        name, qty, unit = _parse_item_text("250ml cream")
        assert name == "cream"
        assert qty == 250
        assert unit == "ml"
