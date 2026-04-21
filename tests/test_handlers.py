"""Tests for bot.handlers — command dispatch and integration."""

import pytest

from bot.config import Config, MastodonConfig, BotConfig, AliasConfig
from bot.handlers import handle
from bot.parser import Item, ParsedCommand
from bot import database as db


@pytest.fixture
def config():
    return Config(
        mastodon=MastodonConfig(
            instance_url="https://example.social",
            access_token="test_token",
        ),
        bot=BotConfig(),
        aliases=AliasConfig(),
    )


USER = "testuser@example.social"


class TestAddHandler:
    def test_add_item(self, tmp_db, config):
        cmd = ParsedCommand(command="add", items=[Item(name="milk", quantity=2)])
        reply = handle(cmd, USER, config, tmp_db)
        assert "Added" in reply
        assert "milk" in reply
        items = db.list_items(tmp_db)
        assert len(items) == 1

    def test_add_item_with_unit(self, tmp_db, config):
        cmd = ParsedCommand(
            command="add",
            items=[Item(name="flour", quantity=500, unit="g")],
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "500g flour" in reply

    def test_add_multiple_items(self, tmp_db, config):
        cmd = ParsedCommand(
            command="add",
            items=[
                Item(name="sugar", quantity=500, unit="g"),
                Item(name="apple", quantity=3),
            ],
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "500g sugar" in reply
        assert "apple" in reply
        items = db.list_items(tmp_db)
        assert len(items) == 2
        names = {i["name"] for i in items}
        assert names == {"sugar", "apple"}


class TestListHandler:
    def test_empty_list(self, tmp_db, config):
        cmd = ParsedCommand(command="list")
        reply = handle(cmd, USER, config, tmp_db)
        assert "empty" in reply.lower()

    def test_list_with_items(self, tmp_db, config):
        db.add_item("milk", 1, None, tmp_db)
        cmd = ParsedCommand(command="list")
        reply = handle(cmd, USER, config, tmp_db)
        assert "milk" in reply


class TestRemoveHandler:
    def test_remove_by_number(self, tmp_db, config):
        db.add_item("milk", 1, None, tmp_db)
        cmd = ParsedCommand(command="remove", remove_targets=["1"])
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply
        assert db.list_items(tmp_db) == []

    def test_remove_by_name(self, tmp_db, config):
        db.add_item("milk", 1, None, tmp_db)
        cmd = ParsedCommand(command="remove", remove_targets=["milk"])
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply

    def test_remove_not_found(self, tmp_db, config):
        cmd = ParsedCommand(command="remove", remove_targets=["nope"])
        reply = handle(cmd, USER, config, tmp_db)
        assert "not found" in reply.lower()

    def test_remove_multiple_by_number(self, tmp_db, config):
        for name in ("milk", "bread", "eggs", "apple"):
            db.add_item(name, 1, None, tmp_db)
        cmd = ParsedCommand(command="remove", remove_targets=["1", "2", "3"])
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply
        remaining = [i["name"] for i in db.list_items(tmp_db)]
        assert remaining == ["apple"]

    def test_remove_range(self, tmp_db, config):
        for name in ("a", "b", "c", "d", "e"):
            db.add_item(name, 1, None, tmp_db)
        cmd = ParsedCommand(command="remove", remove_targets=["2", "3", "4"])
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply
        remaining = [i["name"] for i in db.list_items(tmp_db)]
        assert remaining == ["a", "e"]

    def test_remove_mixed_ranges(self, tmp_db, config):
        for name in ("a", "b", "c", "d", "e", "f", "g"):
            db.add_item(name, 1, None, tmp_db)
        cmd = ParsedCommand(
            command="remove", remove_targets=["2", "3", "4", "6", "7"]
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply
        remaining = [i["name"] for i in db.list_items(tmp_db)]
        assert remaining == ["a", "e"]

    def test_remove_partial_not_found(self, tmp_db, config):
        db.add_item("milk", 1, None, tmp_db)
        cmd = ParsedCommand(command="remove", remove_targets=["1", "nope"])
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply
        assert "Not found" in reply
        assert "nope" in reply

    def test_remove_deduplicates(self, tmp_db, config):
        db.add_item("milk", 1, None, tmp_db)
        db.add_item("bread", 1, None, tmp_db)
        cmd = ParsedCommand(
            command="remove", remove_targets=["1", "1", "milk"]
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "Removed" in reply
        remaining = [i["name"] for i in db.list_items(tmp_db)]
        assert remaining == ["bread"]

    def test_undo_remove_multiple(self, tmp_db, config):
        for name in ("milk", "bread", "eggs"):
            db.add_item(name, 1, None, tmp_db)
        handle(
            ParsedCommand(command="remove", remove_targets=["1", "2", "3"]),
            USER, config, tmp_db,
        )
        assert db.list_items(tmp_db) == []

        reply = handle(ParsedCommand(command="undo"), USER, config, tmp_db)
        assert "Undone" in reply
        assert len(db.list_items(tmp_db)) == 3


class TestUpdateHandler:
    def test_update_quantity(self, tmp_db, config):
        db.add_item("milk", 1, None, tmp_db)
        cmd = ParsedCommand(command="update", item_name="milk", update_quantity=5)
        reply = handle(cmd, USER, config, tmp_db)
        assert "5" in reply
        assert db.get_item_quantity("milk", tmp_db) == 5

    def test_update_not_found(self, tmp_db, config):
        cmd = ParsedCommand(command="update", item_name="nope", update_quantity=5)
        reply = handle(cmd, USER, config, tmp_db)
        assert "not found" in reply.lower()


class TestUndoHandler:
    def test_undo_add(self, tmp_db, config):
        cmd_add = ParsedCommand(command="add", items=[Item(name="milk", quantity=1)])
        handle(cmd_add, USER, config, tmp_db)
        assert len(db.list_items(tmp_db)) == 1

        cmd_undo = ParsedCommand(command="undo")
        reply = handle(cmd_undo, USER, config, tmp_db)
        assert "Undone" in reply
        assert db.list_items(tmp_db) == []

    def test_undo_add_multiple(self, tmp_db, config):
        cmd_add = ParsedCommand(
            command="add",
            items=[Item(name="milk"), Item(name="bread"), Item(name="eggs")],
        )
        handle(cmd_add, USER, config, tmp_db)
        assert len(db.list_items(tmp_db)) == 3

        reply = handle(ParsedCommand(command="undo"), USER, config, tmp_db)
        assert "Undone" in reply
        assert db.list_items(tmp_db) == []

    def test_undo_remove(self, tmp_db, config):
        db.add_item("milk", 2, "l", tmp_db)
        cmd_remove = ParsedCommand(command="remove", remove_targets=["1"])
        handle(cmd_remove, USER, config, tmp_db)
        assert db.list_items(tmp_db) == []

        cmd_undo = ParsedCommand(command="undo")
        reply = handle(cmd_undo, USER, config, tmp_db)
        assert "Undone" in reply
        items = db.list_items(tmp_db)
        assert len(items) == 1
        assert items[0]["name"] == "milk"

    def test_undo_nothing(self, tmp_db, config):
        cmd = ParsedCommand(command="undo")
        reply = handle(cmd, USER, config, tmp_db)
        assert "Nothing" in reply

    def test_undo_update(self, tmp_db, config):
        db.add_item("milk", 2, None, tmp_db)
        cmd_update = ParsedCommand(command="update", item_name="milk", update_quantity=10)
        handle(cmd_update, USER, config, tmp_db)

        cmd_undo = ParsedCommand(command="undo")
        reply = handle(cmd_undo, USER, config, tmp_db)
        assert "Undone" in reply
        assert db.get_item_quantity("milk", tmp_db) == 2


class TestReminderHandlers:
    def test_add_reminder(self, tmp_db, config):
        cmd = ParsedCommand(
            command="reminder_add",
            reminder_date="2026-05-01",
            reminder_time="14:30",
            reminder_message="buy cake",
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "Reminder set" in reply
        assert db.list_reminders(tmp_db)

    def test_add_reminder_default_time(self, tmp_db, config):
        cmd = ParsedCommand(
            command="reminder_add",
            reminder_date="2026-05-01",
            reminder_time=None,
            reminder_message="buy cake",
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "07:30" in reply

    def test_list_reminders_empty(self, tmp_db, config):
        cmd = ParsedCommand(command="reminder_list")
        reply = handle(cmd, USER, config, tmp_db)
        assert "No reminders" in reply

    def test_delete_reminder(self, tmp_db, config):
        db.add_reminder("2026-05-01T05:30:00+00:00", "cake", tmp_db)
        cmd = ParsedCommand(command="reminder_delete", reminder_number=1)
        reply = handle(cmd, USER, config, tmp_db)
        assert "Deleted" in reply

    def test_delete_all_reminders(self, tmp_db, config):
        db.add_reminder("2026-05-01T05:30:00+00:00", "a", tmp_db)
        db.add_reminder("2026-05-02T05:30:00+00:00", "b", tmp_db)
        cmd = ParsedCommand(command="reminder_delete_all")
        reply = handle(cmd, USER, config, tmp_db)
        assert "Deleted all" in reply
        assert db.list_reminders(tmp_db) == []

    def test_undo_reminder_add(self, tmp_db, config):
        cmd = ParsedCommand(
            command="reminder_add",
            reminder_date="2026-05-01",
            reminder_time="14:30",
            reminder_message="cake",
        )
        handle(cmd, USER, config, tmp_db)
        assert len(db.list_reminders(tmp_db)) == 1

        reply = handle(ParsedCommand(command="undo"), USER, config, tmp_db)
        assert "Undone" in reply
        assert db.list_reminders(tmp_db) == []

    def test_undo_reminder_delete(self, tmp_db, config):
        db.add_reminder("2026-05-01T05:30:00+00:00", "cake", tmp_db)
        handle(ParsedCommand(command="reminder_delete", reminder_number=1), USER, config, tmp_db)
        assert db.list_reminders(tmp_db) == []

        reply = handle(ParsedCommand(command="undo"), USER, config, tmp_db)
        assert "Undone" in reply
        assert len(db.list_reminders(tmp_db)) == 1

    def test_undo_reminder_delete_all(self, tmp_db, config):
        db.add_reminder("2026-05-01T05:30:00+00:00", "a", tmp_db)
        db.add_reminder("2026-05-02T05:30:00+00:00", "b", tmp_db)
        handle(ParsedCommand(command="reminder_delete_all"), USER, config, tmp_db)

        reply = handle(ParsedCommand(command="undo"), USER, config, tmp_db)
        assert "Undone" in reply
        assert len(db.list_reminders(tmp_db)) == 2


class TestClearHandler:
    def test_clear_list(self, tmp_db, config):
        for name in ("milk", "bread", "eggs"):
            db.add_item(name, 1, None, tmp_db)
        cmd = ParsedCommand(command="clear")
        reply = handle(cmd, USER, config, tmp_db)
        assert "cleared" in reply.lower()
        assert "3" in reply
        assert db.list_items(tmp_db) == []

    def test_clear_empty_list(self, tmp_db, config):
        cmd = ParsedCommand(command="clear")
        reply = handle(cmd, USER, config, tmp_db)
        assert "already empty" in reply.lower()

    def test_undo_clear(self, tmp_db, config):
        for name in ("milk", "bread"):
            db.add_item(name, 1, None, tmp_db)
        handle(ParsedCommand(command="clear"), USER, config, tmp_db)
        assert db.list_items(tmp_db) == []

        reply = handle(ParsedCommand(command="undo"), USER, config, tmp_db)
        assert "Undone" in reply
        assert len(db.list_items(tmp_db)) == 2


class TestHelpHandler:
    def test_help(self, tmp_db, config):
        cmd = ParsedCommand(command="help")
        reply = handle(cmd, USER, config, tmp_db)
        assert "/list" in reply
        assert "/remove" in reply


class TestUnknownHandler:
    def test_unknown(self, tmp_db, config):
        cmd = ParsedCommand(command="unknown")
        reply = handle(cmd, USER, config, tmp_db)
        assert "/help" in reply


class TestInvalidReminderDate:
    def test_bad_date(self, tmp_db, config):
        cmd = ParsedCommand(
            command="reminder_add",
            reminder_date="not-a-date",
            reminder_time="14:30",
            reminder_message="test",
        )
        reply = handle(cmd, USER, config, tmp_db)
        assert "Invalid" in reply
