# Mastodon Shopping Bot — Project Definition

## Overview

A Mastodon bot that runs as a background service, listens for direct messages
addressed to it, and manages a shared shopping list and a set of scheduled
reminders. All interaction happens via DM using a simple command syntax.

---

## Bot interaction model

- Users interact by sending a DM to the bot account (e.g. `@shop@instance.social`).
- The bot replies to every command with a confirmation or the requested output.
- Commands are case-insensitive.
- Unrecognised messages are treated as items to add to the shopping list.

---

## Shopping list

### Add an item

```
@shop apple
@shop 500g flour
```

Adds the item as free text to the shopping list and confirms with a reply.

### List items

```
@shop /list
```

Replies with a formatted table, e.g.:

```
No. │ Item
────┼──────────
  1 │ apple
  2 │ 500g flour
  3 │ butter
```

Items are numbered by insertion order. Numbers are **reassigned** after each
removal (no gaps).

### Remove an item

```
@shop /remove apple       ← by name (first match, case-insensitive)
@shop /remove 1           ← by list number
```

Confirms removal with a reply.

---

## Reminders

### Add a reminder

```
@shop /reminder 2025-04-01 buy apples
@shop /reminder 2025-04-01 08:30 buy apples
```

- Date format: `YYYY-MM-DD`
- Optional time: `HH:MM` (24-hour). Defaults to the configured default time
  (default: `07:30`).
- Everything after the date (and optional time) is the reminder message.
- At the specified date/time the bot posts the reminder to the configured
  audience (see open questions).

### List reminders

```
@shop /reminder list
```

Replies with a numbered list sorted by date/time ascending, e.g.:

```
No. │ Date/Time        │ Message
────┼──────────────────┼───────────────
  1 │ 2025-04-01 07:30 │ buy apples
  2 │ 2025-05-10 08:30 │ dentist
```

### Delete reminders

```
@shop /reminder delete 1      ← by list number
@shop /reminder delete all    ← remove all reminders
```

---

## Undo

```
@shop /undo
```

Reverses the **last** action taken by the requesting user. Applies to:

- Adding a shopping list item
- Removing a shopping list item
- Adding a reminder
- Deleting a reminder (single)

"Delete all reminders" can also be undone (restores all deleted reminders).

Only one level of undo is supported per user.

---

## Command table with i18n aliases

All commands support an alias in a foreign language, configured in the config
file. Default aliases are German. Aliases are full replacements for the
English keyword.

| English keyword         | Default alias (DE)       |
|-------------------------|--------------------------|
| `/list`                 | `/liste`                 |
| `/remove`               | `/streiche`              |
| `/reminder`             | `/erinnerung`            |
| `/reminder list`        | `/erinnerung liste`      |
| `/reminder delete`      | `/erinnerung loesche`    |
| `/reminder delete all`  | `/erinnerung alle`       |
| `/undo`                 | `/rueckgaengig`          |
| `/help`                 | `/hilfe`                 |

---

## Help command

```
@shop /help
```

Replies with a brief list of all available commands.

---

## Configuration file

Format: TOML (human-friendly, supports comments).

```toml
[mastodon]
instance_url   = "https://mastodon.social"
access_token   = "your_access_token_here"

[bot]
default_reminder_time = "07:30"   # HH:MM, 24-hour
timezone              = "Europe/Berlin"

[aliases]
# Override any default alias here.
# Format: english_keyword = "alias"
list             = "liste"
remove           = "streiche"
reminder         = "erinnerung"
reminder_list    = "liste"         # sub-command of /reminder
reminder_delete  = "loesche"       # sub-command of /reminder
reminder_all     = "alle"          # for /reminder delete all
undo             = "rueckgaengig"
help             = "hilfe"
```

---

## Storage

- **Backend**: SQLite with WAL mode and foreign key enforcement.
- **Shopping list**: shared across all users (one global list).
- **Reminders**: global, visible and manageable by any user.
- **Undo state**: per-user, stores the inverse of the last action.

---

## Technical stack (proposed)

| Concern         | Choice                              |
|-----------------|-------------------------------------|
| Language        | Python 3.12+                        |
| Mastodon API    | `Mastodon.py`                       |
| Scheduler       | `APScheduler` (in-process)          |
| Storage         | SQLite via `sqlite3` stdlib         |
| Config          | `tomllib` (stdlib, Python 3.11+)    |
| Deployment      | Single long-running process         |

Mastodon DM listening: streaming API preferred; polling as fallback.

---

## Open questions — specification gaps

The following items are **missing or ambiguous** in the current spec and need
answers before implementation begins:

### 1. Shared list or per-user list?
Is the shopping list shared by everyone who DMs the bot (one household list),
or does each user have their own private list? The reminder phrasing
"reminding everyone listening" suggests a shared model.

### 2. Who receives reminder notifications?
When a reminder fires, where does the bot post it?
- DM back to the user who created it?
- DM to all users who have ever interacted with the bot?
- A public toot or followers-only toot on the bot account?

### 3. Timezone
Whose timezone is used for reminder scheduling — the bot server's, or a
configurable value? (The config above proposes a configurable `timezone`.)

### 4. Duplicate items on the shopping list
If a user adds "apple" when "apple" is already on the list:
- Accept the duplicate (two rows)?
- Reject and notify?
- Increment a quantity?

### 5. Quantities and free-text items
Can items include quantities (e.g. "2 apples", "500g flour")? If so, is
"apple" and "2 apples" the same item for the purpose of `/remove apple`?

### 6. Access control
Can any Mastodon account DM the bot, or is access restricted to a whitelist
of accounts?

### 7. Undo depth
Is undo limited to exactly **one** level (last command only), or should a
full undo stack be supported?

### 8. Bot response language
Are bot replies always in English, or should they follow the configured alias
language (e.g. replies in German when aliases are German)?

### 9. Reminder recurrence
Are reminders one-shot (fire once, then gone), or can they repeat
(daily/weekly)? Not mentioned in spec.

### 10. Error reply behaviour
What should the bot reply when:
- A `/remove` target doesn't exist?
- A reminder date is in the past?
- A command is completely unrecognised?

### 11. `/remove` by name — partial match?
If the list has "apple" and "apple juice", does `/remove apple` remove the
first exact match, or refuse because it's ambiguous?
