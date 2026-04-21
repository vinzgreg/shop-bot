"""Tests for bot.config and bot.main helpers."""

import pytest
from pathlib import Path

from bot.config import load_config


class TestLoadConfig:
    def test_valid_config(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("""
[mastodon]
instance_url = "https://example.social"
access_token = "test_token_123"

[bot]
timezone = "UTC"
log_level = "DEBUG"

[aliases]
list = "liste"
""")
        config = load_config(cfg_file)
        assert config.mastodon.instance_url == "https://example.social"
        assert config.mastodon.access_token == "test_token_123"
        assert config.bot.timezone == "UTC"
        assert config.bot.log_level == "DEBUG"
        assert config.aliases.list == "liste"

    def test_missing_instance_url(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("""
[mastodon]
access_token = "test_token_123"
""")
        with pytest.raises(ValueError, match="instance_url"):
            load_config(cfg_file)

    def test_missing_access_token(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("""
[mastodon]
instance_url = "https://example.social"
""")
        with pytest.raises(ValueError, match="access_token"):
            load_config(cfg_file)

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.toml")

    def test_defaults(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("""
[mastodon]
instance_url = "https://example.social"
access_token = "test_token_123"
""")
        config = load_config(cfg_file)
        assert config.bot.default_reminder_time == "07:30"
        assert config.bot.timezone == "Europe/Berlin"
        assert config.bot.access == "everyone"
        assert config.aliases.remove == "streiche"


class TestHTMLStripping:
    """Test the HTML→plain text conversion from bot.main."""

    def test_strip_tags(self):
        from bot.text import strip_html
        assert strip_html("<p>hello <b>world</b></p>") == "hello world"

    def test_strip_entities(self):
        from bot.text import strip_html
        assert strip_html("1 &amp; 2 &lt; 3") == "1 & 2 < 3"

    def test_empty(self):
        from bot.text import strip_html
        assert strip_html("") == ""

    def test_mastodon_dm_format(self):
        from bot.text import strip_html
        html = '<p><span class="h-card" translate="no"><a href="https://social.example/@shop" class="u-url mention">@<span>shop</span></a></span> milk</p>'
        result = strip_html(html)
        assert "@" in result
        assert "shop" in result
        assert "milk" in result


class TestMentionStripping:
    def test_strip_full_handle(self):
        from bot.text import strip_mention
        result = strip_mention("@shop@mastodon.social milk", "shop@mastodon.social")
        assert result == "milk"

    def test_strip_local_handle(self):
        from bot.text import strip_mention
        result = strip_mention("@shop milk", "shop@mastodon.social")
        assert result == "milk"

    def test_no_mention(self):
        from bot.text import strip_mention
        result = strip_mention("milk", "shop@mastodon.social")
        assert result == "milk"

    def test_case_insensitive(self):
        from bot.text import strip_mention
        result = strip_mention("@Shop@Mastodon.Social milk", "shop@mastodon.social")
        assert result == "milk"
