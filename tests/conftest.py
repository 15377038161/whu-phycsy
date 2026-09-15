from __future__ import annotations

import secrets

import pytest
from flask.testing import FlaskClient
from werkzeug.datastructures import Headers


ORIGINAL_CLIENT_OPEN = FlaskClient.open


@pytest.fixture
def raw_client_open():
    return ORIGINAL_CLIENT_OPEN


@pytest.fixture(autouse=True)
def attach_csrf_to_test_requests(monkeypatch):
    """Make existing test requests exercise CSRF with a real session token."""

    def open_with_csrf(self, *args, **kwargs):
        method = str(kwargs.get("method", "GET")).upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            with self.session_transaction() as test_session:
                token = test_session.setdefault("_csrf_token", secrets.token_urlsafe(32))
            headers = Headers(kwargs.get("headers"))
            headers.setdefault("X-CSRFToken", token)
            kwargs["headers"] = headers
        return ORIGINAL_CLIENT_OPEN(self, *args, **kwargs)

    monkeypatch.setattr(FlaskClient, "open", open_with_csrf)
