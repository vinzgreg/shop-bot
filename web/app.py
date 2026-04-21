"""
Minimal Flask web UI for the shopping list.

Authentication: HTTP Basic Auth, single shared password configured via
[web] password in config.toml (or WEB_PASSWORD env var as override).

Binds to 127.0.0.1 only — intended to sit behind an nginx reverse proxy.
"""

import functools
import logging
import os
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from bot.config import load_config
from bot.database import (
    DB_PATH,
    add_item,
    list_items,
    remove_items_by_ids,
    update_item_quantity,
)

logger = logging.getLogger(__name__)

app = Flask(__name__)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_password() -> str:
    if pw := os.environ.get("WEB_PASSWORD"):
        return pw
    try:
        cfg = load_config()
        return cfg.web.password if cfg.web else ""
    except Exception:
        return ""


def _unauthorized() -> Response:
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Shopping List"'},
    )


def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        password = _get_password()
        if not password:
            logger.error("WEB_PASSWORD not configured — rejecting all requests")
            return _unauthorized()
        auth = request.authorization
        if not auth or auth.password != password:
            return _unauthorized()
        return fn(*args, **kwargs)
    return wrapper


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
@require_auth
def index():
    return render_template("index.html")


@app.get("/api/items")
@require_auth
def api_list():
    return jsonify(list_items(DB_PATH))


@app.post("/api/items")
@require_auth
def api_add():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    quantity = data.get("quantity")
    unit = (data.get("unit") or "").strip() or None
    try:
        quantity = int(quantity) if quantity is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be an integer"}), 400
    item_id = add_item(name, quantity, unit, DB_PATH)
    return jsonify({"id": item_id}), 201


@app.patch("/api/items/<int:item_id>")
@require_auth
def api_update(item_id: int):
    data = request.get_json(force=True)
    if "quantity" not in data:
        return jsonify({"error": "quantity is required"}), 400
    try:
        quantity = int(data["quantity"])
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be an integer"}), 400
    items = {i["id"]: i for i in list_items(DB_PATH)}
    if item_id not in items:
        return jsonify({"error": "not found"}), 404
    update_item_quantity(items[item_id]["name"], quantity, DB_PATH)
    return jsonify({"ok": True})


@app.delete("/api/items/<int:item_id>")
@require_auth
def api_delete(item_id: int):
    removed = remove_items_by_ids([item_id], DB_PATH)
    if not removed:
        return jsonify({"error": "not found"}), 404
    return jsonify({"ok": True})


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host="127.0.0.1", port=8080)
