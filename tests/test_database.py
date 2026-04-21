"""Tests for bot.database — SQLite persistence layer."""

import pytest

from bot import database as db


class TestAddItem:
    def test_add_new_item(self, tmp_db):
        item_id = db.add_item("milk", 2, None, tmp_db)
        assert item_id is not None
        items = db.list_items(tmp_db)
        assert len(items) == 1
        assert items[0]["name"] == "milk"
        assert items[0]["quantity"] == 2

    def test_add_item_with_unit(self, tmp_db):
        db.add_item("flour", 500, "g", tmp_db)
        items = db.list_items(tmp_db)
        assert items[0]["quantity_unit"] == "g"

    def test_add_duplicate_increments_quantity(self, tmp_db):
        db.add_item("milk", 2, None, tmp_db)
        db.add_item("milk", 3, None, tmp_db)
        items = db.list_items(tmp_db)
        assert len(items) == 1
        assert items[0]["quantity"] == 5  # 2 + 3

    def test_add_duplicate_case_insensitive(self, tmp_db):
        db.add_item("Milk", 1, None, tmp_db)
        db.add_item("milk", 1, None, tmp_db)
        items = db.list_items(tmp_db)
        assert len(items) == 1
        assert items[0]["quantity"] == 2

    def test_add_no_quantity(self, tmp_db):
        db.add_item("bread", None, None, tmp_db)
        items = db.list_items(tmp_db)
        assert items[0]["quantity"] is None

    def test_add_duplicate_no_quantity_increments_by_one(self, tmp_db):
        db.add_item("bread", None, None, tmp_db)
        db.add_item("bread", None, None, tmp_db)
        items = db.list_items(tmp_db)
        assert len(items) == 1
        assert items[0]["quantity"] == 2  # (None or 1) + (None or 1)


class TestListItems:
    def test_empty_list(self, tmp_db):
        assert db.list_items(tmp_db) == []

    def test_ordered_by_id(self, tmp_db):
        db.add_item("banana", None, None, tmp_db)
        db.add_item("apple", None, None, tmp_db)
        items = db.list_items(tmp_db)
        assert items[0]["name"] == "banana"
        assert items[1]["name"] == "apple"


class TestRemoveItem:
    def test_remove_by_number(self, tmp_db):
        db.add_item("milk", 1, None, tmp_db)
        db.add_item("bread", 1, None, tmp_db)
        removed = db.remove_item_by_number(1, tmp_db)
        assert removed["name"] == "milk"
        assert len(db.list_items(tmp_db)) == 1

    def test_remove_by_number_out_of_range(self, tmp_db):
        db.add_item("milk", 1, None, tmp_db)
        assert db.remove_item_by_number(5, tmp_db) is None
        assert db.remove_item_by_number(0, tmp_db) is None

    def test_remove_by_name(self, tmp_db):
        db.add_item("milk", 1, None, tmp_db)
        removed = db.remove_item_by_name("milk", tmp_db)
        assert removed["name"] == "milk"
        assert db.list_items(tmp_db) == []

    def test_remove_by_name_case_insensitive(self, tmp_db):
        db.add_item("Milk", 1, None, tmp_db)
        removed = db.remove_item_by_name("milk", tmp_db)
        assert removed is not None

    def test_remove_by_name_not_found(self, tmp_db):
        assert db.remove_item_by_name("nope", tmp_db) is None


class TestUpdateItemQuantity:
    def test_update_existing(self, tmp_db):
        db.add_item("milk", 1, None, tmp_db)
        assert db.update_item_quantity("milk", 5, tmp_db) is True
        assert db.get_item_quantity("milk", tmp_db) == 5

    def test_update_not_found(self, tmp_db):
        assert db.update_item_quantity("nope", 5, tmp_db) is False


class TestGetItemQuantity:
    def test_existing(self, tmp_db):
        db.add_item("milk", 3, None, tmp_db)
        assert db.get_item_quantity("milk", tmp_db) == 3

    def test_not_found(self, tmp_db):
        assert db.get_item_quantity("nope", tmp_db) is None


class TestRestoreItem:
    def test_restore(self, tmp_db):
        db.restore_item("milk", 2, "l", tmp_db)
        items = db.list_items(tmp_db)
        assert len(items) == 1
        assert items[0]["name"] == "milk"
        assert items[0]["quantity"] == 2
        assert items[0]["quantity_unit"] == "l"


class TestReminders:
    def test_add_and_list(self, tmp_db):
        rid = db.add_reminder("2026-05-01T07:30:00+00:00", "buy cake", tmp_db)
        assert rid is not None
        reminders = db.list_reminders(tmp_db)
        assert len(reminders) == 1
        assert reminders[0]["message"] == "buy cake"

    def test_list_excludes_fired(self, tmp_db):
        rid = db.add_reminder("2026-05-01T07:30:00+00:00", "msg", tmp_db)
        db.mark_reminder_fired(rid, tmp_db)
        assert db.list_reminders(tmp_db) == []

    def test_delete_by_number(self, tmp_db):
        db.add_reminder("2026-05-01T07:30:00+00:00", "first", tmp_db)
        db.add_reminder("2026-05-02T07:30:00+00:00", "second", tmp_db)
        deleted = db.delete_reminder_by_number(1, tmp_db)
        assert deleted["message"] == "first"
        assert len(db.list_reminders(tmp_db)) == 1

    def test_delete_by_number_out_of_range(self, tmp_db):
        assert db.delete_reminder_by_number(1, tmp_db) is None

    def test_delete_all(self, tmp_db):
        db.add_reminder("2026-05-01T07:30:00+00:00", "a", tmp_db)
        db.add_reminder("2026-05-02T07:30:00+00:00", "b", tmp_db)
        deleted = db.delete_all_reminders(tmp_db)
        assert len(deleted) == 2
        assert db.list_reminders(tmp_db) == []

    def test_delete_all_empty(self, tmp_db):
        assert db.delete_all_reminders(tmp_db) == []

    def test_restore_reminder(self, tmp_db):
        db.restore_reminder("2026-05-01T07:30:00+00:00", "restored", tmp_db)
        reminders = db.list_reminders(tmp_db)
        assert len(reminders) == 1
        assert reminders[0]["message"] == "restored"

    def test_get_due_reminders(self, tmp_db):
        db.add_reminder("2020-01-01T00:00:00+00:00", "past", tmp_db)
        db.add_reminder("2099-01-01T00:00:00+00:00", "future", tmp_db)
        due = db.get_due_reminders("2026-04-21T12:00:00+00:00", tmp_db)
        assert len(due) == 1
        assert due[0]["message"] == "past"

    def test_mark_fired(self, tmp_db):
        rid = db.add_reminder("2020-01-01T00:00:00+00:00", "past", tmp_db)
        db.mark_reminder_fired(rid, tmp_db)
        due = db.get_due_reminders("2026-04-21T12:00:00+00:00", tmp_db)
        assert len(due) == 0

    def test_delete_by_id(self, tmp_db):
        rid = db.add_reminder("2026-05-01T07:30:00+00:00", "msg", tmp_db)
        db.delete_reminder_by_id(rid, tmp_db)
        assert db.list_reminders(tmp_db) == []


class TestUndoState:
    def test_set_and_get(self, tmp_db):
        db.set_undo("@user", "add", {"item_name": "milk"}, tmp_db)
        result = db.get_and_clear_undo("@user", tmp_db)
        assert result is not None
        action_type, data = result
        assert action_type == "add"
        assert data["item_name"] == "milk"

    def test_get_clears(self, tmp_db):
        db.set_undo("@user", "add", {"item_name": "milk"}, tmp_db)
        db.get_and_clear_undo("@user", tmp_db)
        assert db.get_and_clear_undo("@user", tmp_db) is None

    def test_replaces_previous(self, tmp_db):
        db.set_undo("@user", "add", {"item_name": "milk"}, tmp_db)
        db.set_undo("@user", "remove", {"name": "bread"}, tmp_db)
        action_type, data = db.get_and_clear_undo("@user", tmp_db)
        assert action_type == "remove"

    def test_no_undo_state(self, tmp_db):
        assert db.get_and_clear_undo("@nobody", tmp_db) is None


class TestInteractionLog:
    def test_log_interaction(self, tmp_db):
        # Should not raise
        db.log_interaction("@user", "hello", tmp_db)
