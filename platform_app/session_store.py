"""Server-side session backend for the _sid URL-ticket session mechanism.

The platform proxy strips Set-Cookie response headers and inbound Cookie
request headers, which breaks Flask's default cookie-based session. This
module replaces it with a database-backed session:

- The session id (_sid) is carried in the URL query string / form body /
  X-Session-Id header and propagated by static/sid.js on the client.
- Session payloads are stored in the app_sessions table with a 12h TTL.
- Direct (non-proxied) access still receives a Set-Cookie header, so local
  development keeps working with cookies alone.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from flask.sessions import SessionInterface, SessionMixin
from flask import g, request
from sqlalchemy import delete, select

SESSION_TTL_HOURS = 12
_SID_MAX_LEN = 96


class ServerSession(dict, SessionMixin):
    """Dict-backed session object compatible with Flask's session API."""

    def __init__(self, initial=None, sid: str = ""):
        super().__init__(initial or {})
        self.sid = sid


class NullSession(ServerSession):
    """Marker type for 'no session' so Flask's isinstance check in
    process_response never matches real ServerSession instances."""

    def _fail(self, *args, **kwargs):
        raise RuntimeError("NullSession is read-only")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _fail


class TicketSessionInterface(SessionInterface):
    """Flask SessionInterface persisting data in the app_sessions table."""

    null_session_class = NullSession

    def open_session(self, app, request):
        from .db import db_session
        from .models import AppSession

        # NOTE: the platform proxy injects its own cookie literally named
        # "session" — never trust it. Our cookie uses a distinct name.
        sid = (
            request.values.get("_sid")
            or request.headers.get("X-Session-Id")
            or request.cookies.get("whu_sid")
            or ""
        ).strip()
        data: dict = {}
        if sid and len(sid) <= _SID_MAX_LEN:
            row = db_session().get(AppSession, sid)
            if row and row.expires_at > datetime.now(timezone.utc).replace(tzinfo=row.expires_at.tzinfo):
                data = dict(row.data or {})
            else:
                sid = ""
        if not sid:
            sid = secrets.token_urlsafe(32)
        g._sid = sid
        g._session_dirty = bool(data)
        return ServerSession(data, sid=sid)

    def save_session(self, app, session, response):
        from .db import db_session
        from .models import AppSession

        sid = getattr(g, "_sid", None) or getattr(session, "sid", "")
        if not sid:
            return
        # Occasionally purge expired tickets (cheap probabilistic GC).
        if secrets.randbelow(64) == 0:
            db_session().execute(
                delete(AppSession).where(AppSession.expires_at < datetime.now(timezone.utc))
            )

        row = db_session().get(AppSession, sid)
        if not session:
            # Emptied session: keep the ticket alive with empty data so the
            # CSRF token can be re-issued on the next page render.
            payload: dict = {}
        else:
            payload = dict(session)
        expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
        if row is None:
            db_session().add(AppSession(sid=sid, data=payload, expires_at=expires))
        else:
            row.data = payload
            row.expires_at = expires
        db_session().commit()

        # Best effort: direct (non-proxied) clients also get a cookie so they
        # don't need URL tickets at all. The proxy strips this header, which
        # is exactly the case where _sid propagation takes over.
        if not response.headers.get("Set-Cookie"):
            response.set_cookie(
                "whu_sid",
                sid,
                max_age=SESSION_TTL_HOURS * 3600,
                httponly=True,
                samesite="Lax",
                secure=app.config["APP_ENV"] == "production",
            )


def current_sid() -> str:
    """Sid for the active request (empty string outside a request context)."""
    return getattr(g, "_sid", "")
