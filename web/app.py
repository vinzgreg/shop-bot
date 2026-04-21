"""
Minimal Flask web UI for the shopping list.

Authentication: HTTP Basic Auth, single shared password configured via
WEB_PASSWORD environment variable (preferred) or [web] password in
config.toml.  Intended to sit behind an nginx reverse proxy that
terminates TLS.
"""

import functools
import logging
import os
import secrets
from urllib.parse import urlparse

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

# State-changing HTTP methods that require an Origin check (CSRF defence).
_UNSAFE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_password() -> str:
    """Return the configured web password, or '' if none is configured."""
    if pw := os.environ.get("WEB_PASSWORD"):
        return pw
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load config while resolving web password")
        return ""
    return cfg.web.password if cfg.web else ""


def _unauthorized() -> Response:
    return Response(
        "Authentication required",
        401,
        {"WWW-Authenticate": 'Basic realm="Shopping List"'},
    )


def _origin_ok() -> bool:
    """
    CSRF defence: for state-changing requests, require that the Origin
    (or Referer) header matches the Host header.  Browsers attach the
    Origin header automatically to cross-origin non-GET requests.
    """
    if request.method not in _UNSAFE_METHODS:
        return True
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source:
        return False
    try:
        source_host = urlparse(source).netloc
    except ValueError:
        return False
    return bool(source_host) and source_host == request.host


def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        password = _get_password()
        if not password:
            logger.error("WEB_PASSWORD not configured — rejecting all requests")
            return _unauthorized()
        auth = request.authorization
        if not auth or not auth.password or not secrets.compare_digest(
            auth.password, password
        ):
            return _unauthorized()
        if not _origin_ok():
            logger.warning(
                "Rejecting %s %s: Origin/Referer mismatch (host=%s)",
                request.method, request.path, request.host,
            )
            return jsonify({"error": "cross-origin request blocked"}), 403
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


_MAX_NAME_LEN = 200
_MAX_UNIT_LEN = 40


def _parse_json():
    """Return the request JSON body, or None if missing/invalid."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@app.post("/api/items")
@require_auth
def api_add():
    data = _parse_json()
    if data is None:
        return jsonify({"error": "invalid JSON body"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if len(name) > _MAX_NAME_LEN:
        return jsonify({"error": f"name too long (max {_MAX_NAME_LEN})"}), 400
    unit_raw = (data.get("unit") or "").strip()
    if len(unit_raw) > _MAX_UNIT_LEN:
        return jsonify({"error": f"unit too long (max {_MAX_UNIT_LEN})"}), 400
    unit = unit_raw or None
    quantity_raw = data.get("quantity")
    try:
        quantity = int(quantity_raw) if quantity_raw is not None else None
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be an integer"}), 400
    if quantity is not None and quantity < 1:
        return jsonify({"error": "quantity must be positive"}), 400
    item_id = add_item(name, quantity, unit, DB_PATH)
    return jsonify({"id": item_id}), 201


@app.patch("/api/items/<int:item_id>")
@require_auth
def api_update(item_id: int):
    data = _parse_json()
    if data is None:
        return jsonify({"error": "invalid JSON body"}), 400
    if "quantity" not in data:
        return jsonify({"error": "quantity is required"}), 400
    try:
        quantity = int(data["quantity"])
    except (TypeError, ValueError):
        return jsonify({"error": "quantity must be an integer"}), 400
    if quantity < 1:
        return jsonify({"error": "quantity must be positive"}), 400
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
    app.run(host="0.0.0.0", port=8080)
