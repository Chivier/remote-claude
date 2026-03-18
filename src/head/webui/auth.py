"""Simple authentication middleware for WebUI.

Rules:
- If bind is 127.0.0.1 (localhost only): no auth required.
- If bind is 0.0.0.0 (remote access): require password via session cookie.
- Password hash stored in ~/.codecast/webui_secret.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from pathlib import Path
from typing import Optional

from aiohttp import web

logger = logging.getLogger(__name__)

SECRET_FILE = Path.home() / ".codecast" / "webui_secret"


def _load_secret() -> Optional[str]:
    """Load the stored password hash, or None if not set."""
    try:
        return SECRET_FILE.read_text().strip()
    except FileNotFoundError:
        return None


def _hash_password(password: str) -> str:
    """Hash a password for storage."""
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against a stored hash."""
    parts = stored.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected_hash = parts
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hmac.compare_digest(h, expected_hash)


def set_password(password: str) -> None:
    """Set the WebUI password."""
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_FILE.write_text(_hash_password(password))
    logger.info("WebUI password updated")


def requires_auth(bind: str) -> bool:
    """Check if authentication is required based on bind address."""
    return bind != "127.0.0.1"


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Middleware that enforces authentication when binding to 0.0.0.0."""
    app = request.app
    bind = app.get("bind", "127.0.0.1")

    if not requires_auth(bind):
        return await handler(request)

    # Allow static files without auth
    if request.path.startswith("/static/"):
        return await handler(request)

    # Allow login page
    if request.path == "/login":
        return await handler(request)

    # Check session cookie
    session_token = request.cookies.get("codecast_session")
    valid_tokens: set = app.get("session_tokens", set())

    if session_token and session_token in valid_tokens:
        return await handler(request)

    # Not authenticated -- redirect to login
    raise web.HTTPFound("/login")
