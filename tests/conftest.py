"""Shared fixtures for all test modules."""

import tempfile
from pathlib import Path

import pytest

from bot.config import AliasConfig
from bot.database import init_db


@pytest.fixture
def tmp_db(tmp_path):
    """Return a Path to a fresh, initialised SQLite database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def aliases():
    """Return default German alias config."""
    return AliasConfig()
