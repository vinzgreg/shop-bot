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
        assert len(cmd.items) == 1
        assert cmd.items[0].name == "milk"
        assert cmd.items[0].quantity is None
        assert cmd.items[0].unit is None

    def test_quantity_and_item(self, aliases):
        cmd = parse("2 apples", aliases)
        assert cmd.command == "add"
        assert cmd.items[0].name == "apples"
        assert cmd.items[0].quantity == 2
        assert cmd.items[0].unit is None

    def test_quantity_with_unit(self, aliases):
        cmd = parse("500g flour", aliases)
        assert cmd.command == "add"
        assert cmd.items[0].name == "flour"
        assert cmd.items[0].quantity == 500
        assert cmd.items[0].unit == "g"

    def test_quantity_with_unit_kg(self, aliases):
        cmd = parse("2kg potatoes", aliases)
        assert cmd.command == "add"
        assert cmd.items[0].name == "potatoes"
        assert cmd.items[0].quantity == 2
        assert cmd.items[0].unit == "kg"

    def test_float_quantity_truncates(self, aliases):
        cmd = parse("1.5l milk", aliases)
        assert cmd.command == "add"
        assert cmd.items[0].name == "milk"
        assert cmd.items[0].quantity == 1  # int(float("1.5")) = 1
        assert cmd.items[0].unit == "l"

    def test_multiword_item(self, aliases):
        cmd = parse("brown sugar", aliases)
        assert cmd.command == "add"
        assert len(cmd.items) == 1
        assert cmd.items[0].name == "brown sugar"

    def test_comma_separated_items(self, aliases):
        cmd = parse("apple, pea", aliases)
        assert cmd.command == "add"
        assert [i.name for i in cmd.items] == ["apple", "pea"]
        assert all(i.quantity is None and i.unit is None for i in cmd.items)

    def test_comma_separated_with_quantities(self, aliases):
        cmd = parse("500g sugar, 3 apple", aliases)
        assert cmd.command == "add"
        assert len(cmd.items) == 2
        assert cmd.items[0].name == "sugar"
        assert cmd.items[0].quantity == 500
        assert cmd.items[0].unit == "g"
        assert cmd.items[1].name == "apple"
        assert cmd.items[1].quantity == 3
        assert cmd.items[1].unit is None

    def test_comma_trailing_and_empty_pieces(self, aliases):
        cmd = parse("apple, , pea,", aliases)
        assert cmd.command == "add"
        assert [i.name for i in cmd.items] == ["apple", "pea"]

    def test_comma_no_spaces(self, aliases):
        cmd = parse("apple,pea", aliases)
        assert cmd.command == "add"
        assert [i.name for i in cmd.items] == ["apple", "pea"]


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
        assert cmd.remove_targets == ["3"]

    def test_remove_by_name(self, aliases):
        cmd = parse("/remove milk", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["milk"]

    def test_remove_comma_list(self, aliases):
        cmd = parse("/remove 1, 2, 3", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["1", "2", "3"]

    def test_remove_range(self, aliases):
        cmd = parse("/remove 2-4", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["2", "3", "4"]

    def test_remove_mixed_ranges(self, aliases):
        cmd = parse("/remove 2-4, 6-7", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["2", "3", "4", "6", "7"]

    def test_remove_mixed_names_and_numbers(self, aliases):
        cmd = parse("/remove 1, milk, 3-4", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["1", "milk", "3", "4"]

    def test_remove_reversed_range_is_swapped(self, aliases):
        cmd = parse("/remove 5-3", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["3", "4", "5"]

    def test_delete_no_args_clears_list(self, aliases):
        cmd = parse("/delete", aliases)
        assert cmd.command == "clear"

    def test_delete_with_number(self, aliases):
        cmd = parse("/delete 2", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["2"]

    def test_delete_with_multi(self, aliases):
        cmd = parse("/delete 1, 2, 3", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["1", "2", "3"]

    def test_delete_with_range(self, aliases):
        cmd = parse("/delete 2-4, 6-7", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["2", "3", "4", "6", "7"]

    def test_delete_with_name(self, aliases):
        cmd = parse("/delete milk", aliases)
        assert cmd.command == "remove"
        assert cmd.remove_targets == ["milk"]


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
        assert cmd.remove_targets == ["milk"]

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
