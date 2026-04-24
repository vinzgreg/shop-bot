"""Load and validate bot configuration from config.toml."""

import logging
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("/app/config/config.toml")


@dataclass
class MastodonConfig:
    instance_url: str
    access_token: str


@dataclass
class BotConfig:
    default_reminder_time: str = "07:30"  # HH:MM, 24-hour
    timezone: str = "Europe/Berlin"
    log_level: str = "INFO"
    access: str = "everyone"              # "everyone" or "followers_only"


@dataclass
class AliasConfig:
    """Localised command aliases (defaults: German)."""
    list: str = "liste"
    remove: str = "streiche"
    update: str = "aktualisiere"
    reminder: str = "erinnerung"
    reminder_list: str = "liste"
    reminder_delete: str = "loesche"
    reminder_all: str = "alle"
    reminder_tomorrow: str = "morgen"
    undo: str = "undo"
    help: str = "hilfe"


@dataclass
class WebConfig:
    password: str = ""       # shared Basic Auth password; required when web UI is enabled
    port: int = 8080         # internal port the Flask app listens on


@dataclass
class Config:
    mastodon: MastodonConfig
    bot: BotConfig
    aliases: AliasConfig
    web: WebConfig = field(default_factory=WebConfig)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read config.toml and return a validated Config object."""
    logger.debug("Loading config from %s", path)

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    masto = raw.get("mastodon", {})
    if not masto.get("instance_url"):
        raise ValueError("mastodon.instance_url is required in config.toml")
    if not masto.get("access_token"):
        raise ValueError("mastodon.access_token is required in config.toml")

    mastodon_cfg = MastodonConfig(
        instance_url=masto["instance_url"],
        access_token=masto["access_token"],
    )

    b = raw.get("bot", {})
    bot_cfg = BotConfig(
        default_reminder_time=b.get("default_reminder_time", "07:30"),
        timezone=b.get("timezone", "Europe/Berlin"),
        log_level=b.get("log_level", "INFO"),
        access=b.get("access", "everyone"),
    )

    a = raw.get("aliases", {})
    aliases_cfg = AliasConfig(
        list=a.get("list", "liste"),
        remove=a.get("remove", "streiche"),
        update=a.get("update", "aktualisiere"),
        reminder=a.get("reminder", "erinnerung"),
        reminder_list=a.get("reminder_list", "liste"),
        reminder_delete=a.get("reminder_delete", "loesche"),
        reminder_all=a.get("reminder_all", "alle"),
        reminder_tomorrow=a.get("reminder_tomorrow", "morgen"),
        undo=a.get("undo", "undo"),
        help=a.get("help", "hilfe"),
    )

    w = raw.get("web", {})
    web_cfg = WebConfig(
        password=w.get("password", ""),
        port=int(w.get("port", 8080)),
    )

    logger.info(
        "Config loaded: instance=%s access=%s log_level=%s timezone=%s",
        mastodon_cfg.instance_url,
        bot_cfg.access,
        bot_cfg.log_level,
        bot_cfg.timezone,
    )
    return Config(mastodon=mastodon_cfg, bot=bot_cfg, aliases=aliases_cfg, web=web_cfg)
