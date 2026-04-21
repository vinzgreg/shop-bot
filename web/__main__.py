import logging
import os
from web.app import app, _get_password

logging.basicConfig(level=logging.INFO)

if not _get_password():
    raise SystemExit("WEB_PASSWORD is not set — refusing to start without authentication")

port = int(os.environ.get("WEB_PORT", 8080))
app.run(host="0.0.0.0", port=port)
