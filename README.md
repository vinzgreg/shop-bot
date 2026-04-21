# Shop Bot

A Mastodon bot that manages a shared shopping list and scheduled reminders via direct messages.

![Shop Bot](shop-bot.png)

---

## Capabilities

### Shopping list

The shopping list is **shared** — all users who DM the bot see and modify the same list.

| Command | Description |
|---|---|
| `@shop apple` | Add "apple" to the list |
| `@shop 2 apples` | Add with quantity |
| `@shop 500g flour` | Add with unit quantity |
| `@shop 500g sugar, 3 apple` | Add several items at once (comma-separated) |
| `@shop /list` | Show the full list |
| `@shop /remove apple` | Remove by name (first exact match) |
| `@shop /remove 1` | Remove by list number |
| `@shop /remove 1, 2, 3` | Remove several items at once |
| `@shop /remove 2-4, 6-7` | Remove items by range(s) |
| `@shop /delete` | Clear the entire shopping list |
| `@shop /delete 1, 2-4` | Remove specific items (same syntax as `/remove`) |
| `@shop /update 4 apple` | Set quantity of an existing item |

Any unrecognised message is treated as an item to add. Adding a duplicate item increments its quantity by 1.

### Reminders

Reminders are **one-shot** and fire as a **public post** on the bot account at the scheduled time.

| Command | Description |
|---|---|
| `@shop /reminder 2025-04-01 buy apples` | Add reminder (uses default time) |
| `@shop /reminder 2025-04-01 08:30 buy apples` | Add reminder with explicit time |
| `@shop /reminder list` | List all upcoming reminders |
| `@shop /reminder delete 1` | Delete reminder by number |
| `@shop /reminder delete all` | Delete all reminders |

### Undo

`@shop /undo` reverses the last action taken by the requesting user (one level only). Works for add/remove shopping items and add/delete reminders.

### Help

`@shop /help` — replies with a summary of all available commands.

### i18n aliases

Every command keyword has a configurable alias (default: German). Both the English keyword and the alias are always accepted. See the `[aliases]` section in the config file.

### Access control

Set `access = "everyone"` to allow any Mastodon account to use the bot, or `access = "followers_only"` to restrict it to accounts that follow the bot.

---

## Requirements

- Docker and Docker Compose
- A Mastodon account for the bot with an OAuth access token

---

## Installation

### 1. Clone the repository

```bash
git clone <repo-url>
cd shop
```

### 2. Create the config file

```bash
mkdir config
cp config.toml.example config/config.toml
```

Edit `config/config.toml` and fill in at minimum:

```toml
[mastodon]
instance_url = "https://mastodon.social"   # URL of your Mastodon instance
access_token = "your_access_token_here"    # bot account OAuth access token
```

To obtain an access token: Mastodon → Settings → Development → New application → copy the access token.

### 3. Create the data directory

```bash
mkdir -p data/shop
```

### 4. Build and start

```bash
docker compose up -d
```

Logs:

```bash
docker compose logs -f
```

---

## Configuration reference

All options are in `config/config.toml` (copy from `config.toml.example`).

### `[mastodon]`

| Key | Description |
|---|---|
| `instance_url` | Full URL of your Mastodon instance, no trailing slash |
| `access_token` | OAuth access token for the bot account |

### `[bot]`

| Key | Default | Description |
|---|---|---|
| `default_reminder_time` | `"07:30"` | Time used for reminders when none is specified (HH:MM, 24-hour) |
| `timezone` | `"Europe/Berlin"` | IANA timezone for scheduling and display |
| `log_level` | `"INFO"` | Log verbosity: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `access` | `"everyone"` | `"everyone"` or `"followers_only"` |

### `[aliases]`

Each key maps an English command keyword to a localised alias. Both forms are accepted at all times. Defaults are German.

| Key | Default alias |
|---|---|
| `list` | `liste` |
| `remove` | `streiche` |
| `update` | `aktualisiere` |
| `reminder` | `erinnerung` |
| `reminder_list` | `liste` |
| `reminder_delete` | `loesche` |
| `reminder_all` | `alle` |
| `undo` | `undo` |
| `help` | `hilfe` |

---

## Data persistence

The SQLite database is stored in `./data/shop/` on the host (mounted into `/app/data/shop` in the container). Back up this directory to preserve the shopping list and reminders.

The config directory (`./config/`) is mounted read-only and never written to by the bot.

---

## Stopping and updating

```bash
# Stop
docker compose down

# Pull latest code and rebuild
git pull
docker compose up -d --build
```
