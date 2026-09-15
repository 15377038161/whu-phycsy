"""Structured logging, per-request access log and request-id correlation.

- Read level from LOG_LEVEL (default ``debug``), emit to stdout/stderr for
  centralized collection.
- Log one access line per request with request_id/method/path(no query)/status/duration_ms.
- Never log Authorization, Cookie or sensitive query params.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from flask import Flask, g, request


def _level() -> int:
    name = (os.getenv("LOG_LEVEL") or "debug").strip().upper()
    return getattr(logging, name, logging.DEBUG)


def setup_logging(app: Flask) -> None:
    """Configure the root logger once; app.logger propagates to it."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(_level())
    # Avoid duplicate handlers if create_app runs more than once in a process.
    if not any(isinstance(h, logging.StreamHandler) and h.stream in (os.sys.stderr, os.sys.stdout) for h in root.handlers):
        root.addHandler(handler)
    app.logger.setLevel(root.level)
    app.logger.propagate = True


def before_request_log() -> None:
    g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_started = time.perf_counter()


def after_request_log(response):
    started = getattr(g, "request_started", time.perf_counter())
    duration_ms = (time.perf_counter() - started) * 1000.0
    rid = getattr(g, "request_id", "-")
    # request.path excludes the query string; never log headers or bodies.
    logging.getLogger("http.access").info(
        "request_id=%s method=%s path=%s status=%d duration_ms=%.1f",
        rid,
        request.method,
        request.path,
        response.status_code,
        duration_ms,
    )
    response.headers.setdefault("X-Request-ID", rid)
    return response


def teardown_request_log(exc=None) -> None:
    if exc is not None:
        logging.getLogger("http.access").error(
            "request_id=%s method=%s path=%s error=%s",
            getattr(g, "request_id", "-"),
            request.method,
            request.path,
            exc,
            exc_info=True,
        )