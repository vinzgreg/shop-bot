"""
Minimal Flask web UI for the shopping list.

Authentication: cookie-based session.  The user POSTs the shared password
to /login; on success a signed session cookie is set with a 30-day
lifetime.  The cookie is HttpOnly, Secure (HTTPS only) and SameSite=Lax,
which provides built-in CSRF protection for state-changing requests.

Required environment variables:
  WEB_PASSWORD     — shared login password
  WEB_SECRET_KEY   — long random string used to sign the session cookie
                     (generate with: python -c 'import secrets; print(secrets.token_urlsafe(48))')

Intended to sit behind an nginx reverse proxy that terminates TLS and
forwards X-Forwarded-Proto / X-Forwarded-Host.
"""

import functools
import logging
import os
import secrets
from datetime import timedelta

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.middleware.proxy_fix import ProxyFix

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

# Trust X-Forwarded-Proto / X-Forwarded-Host from nginx so url_for() and
# the Secure-cookie check see the original https scheme.
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

app.config.update(
    SECRET_KEY=os.environ.get("WEB_SECRET_KEY", ""),
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _get_password() -> str:
    """Return the configured login password, or '' if none is configured."""
    if pw := os.environ.get("WEB_PASSWORD"):
        return pw
    try:
        cfg = load_config()
    except Exception:
        logger.exception("Failed to load config while resolving web password")
        return ""
    return cfg.web.password if cfg.web else ""


def require_auth(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("authed"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "not authenticated"}), 401
            return redirect(url_for("login_form", next=request.path))
        return fn(*args, **kwargs)
    return wrapper


# ── Login / logout ────────────────────────────────────────────────────────────

@app.get("/login")
def login_form():
    if session.get("authed"):
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.post("/login")
def login_submit():
    submitted = (request.form.get("password") or "").strip()
    expected = _get_password()
    if not expected:
        logger.error("WEB_PASSWORD not configured — rejecting login")
        return render_template("login.html", error="Server nicht konfiguriert"), 500
    if not submitted or not secrets.compare_digest(submitted, expected):
        logger.warning("Failed login attempt from %s", request.remote_addr)
        return render_template("login.html", error="Falsches Passwort"), 401
    session.clear()
    session["authed"] = True
    session.permanent = True
    next_url = request.args.get("next") or url_for("index")
    if not next_url.startswith("/"):
        # Only allow same-app relative redirects
        next_url = url_for("index")
    return redirect(next_url)


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_form"))


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
