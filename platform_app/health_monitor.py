"""Long-running connection & dependency health monitoring.

Responsibilities
----------------
1. Startup self-check: verify core runtime dependencies are importable and the
   database / data directory are reachable *before* the app starts serving, so
   a broken deploy fails loudly in the log instead of surfacing as "connection
   refused" or 500 on first hit.
2. Background monitor: a daemon thread periodically re-checks the core
   connections (database + files) and, at a slower cadence, the optional AI
   service. The latest snapshot is exposed through ``/health`` and every
   degraded transition is written to ``health.monitor`` as an ERROR.

The monitor is deliberately lightweight and never crashes the app: any check
failure is caught and recorded, and the snapshot degrades gracefully.
"""

from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("health.monitor")

# Critical runtime dependencies (import name -> distribution name). A missing or
# broken import here means the app cannot serve its core flows.
CORE_DEPENDENCIES: dict[str, str] = {
    "flask": "flask",
    "sqlalchemy": "SQLAlchemy",
    "psycopg": "psycopg",
    "docx": "python-docx",
    "openpyxl": "openpyxl",
    "reportlab": "reportlab",
    "httpx": "httpx",
    "dotenv": "python-dotenv",
}


def check_core_dependencies() -> tuple[bool, list[str]]:
    """Import each core runtime dependency once, returning (ok, failures)."""
    failures: list[str] = []
    for import_name, package_name in CORE_DEPENDENCIES.items():
        try:
            importlib.import_module(import_name)
        except Exception as exc:  # noqa: BLE001 - report and continue
            failures.append(f"{package_name} (import {import_name}) -> {exc}")
    return (not failures), failures


def _database_ready(app) -> bool:
    # db_session()/engine() resolve the DB URL through flask.current_app, which
    # is unavailable in a bare daemon thread. Push an app context explicitly so
    # the background monitor and startup check can reach the real database.
    try:
        from .db import ready as db_ready

        with app.app_context():
            return db_ready()
    except Exception:  # noqa: BLE001
        return False


def _files_ready(app) -> bool:
    try:
        data_dir = Path(app.config["DATA_DIR"])
        return data_dir.exists() and data_dir.is_dir()
    except Exception:  # noqa: BLE001
        return False


def _ai_ready() -> bool:
    # AI is an optional enhancement; a missing/expired config must not mark the
    # core service unhealthy. Import lazily so the monitor never blocks startup.
    try:
        from ai_service import ai_ready

        return ai_ready()
    except Exception:  # noqa: BLE001
        return False


class HealthMonitor:
    """Tracks the latest connection health snapshot in a thread-safe way."""

    def __init__(self, app, core_interval: float = 60.0, ai_interval: float = 300.0):
        self._app = app
        self._core_interval = max(5.0, core_interval)
        self._ai_interval = max(30.0, ai_interval)
        self._lock = threading.Lock()
        self._snapshot: dict[str, object] = {
            "status": "starting",
            "database": None,
            "files": None,
            "ai": None,
            "dependencies": None,
            "last_check_at": None,
            "started_at": time.time(),
        }
        self._ai_checked_at = 0.0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- snapshot access -----------------------------------------------------

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return dict(self._snapshot)

    # -- lifecycle -----------------------------------------------------------

    def run_startup_check(self) -> bool:
        """Synchronous startup self-check; returns True when core is healthy."""
        deps_ok, failures = check_core_dependencies()
        db_ok = _database_ready(self._app)
        files_ok = _files_ready(self._app)
        core_ok = deps_ok and db_ok and files_ok

        with self._lock:
            self._snapshot.update(
                dependencies="ok" if deps_ok else f"failed: {', '.join(failures)}",
                database=db_ok,
                files=files_ok,
                last_check_at=time.time(),
                status="ready" if core_ok else "degraded",
            )

        if not deps_ok:
            logger.error("startup dependency check FAILED: %s", "; ".join(failures))
        if not db_ok:
            logger.error("startup check: database is not reachable")
        if not files_ok:
            logger.error("startup check: data directory is missing or unreadable")
        if core_ok:
            logger.info("startup self-check passed (deps ok, database ok, files ok)")
        return core_ok

    def _check_core(self) -> None:
        db_ok = _database_ready(self._app)
        files_ok = _files_ready(self._app)
        with self._lock:
            self._snapshot.update(
                database=db_ok,
                files=files_ok,
                last_check_at=time.time(),
                status="ready" if db_ok and files_ok else "degraded",
            )
        if not db_ok or not files_ok:
            logger.error(
                "health monitor degraded: database=%s files=%s",
                db_ok,
                files_ok,
            )

    def _check_ai(self) -> None:
        ai_ok = _ai_ready()
        with self._lock:
            self._snapshot["ai"] = ai_ok
        self._ai_checked_at = time.monotonic()
        if not ai_ok:
            logger.warning("health monitor: optional AI service is not ready")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._check_core()
                if time.monotonic() - self._ai_checked_at >= self._ai_interval:
                    self._check_ai()
            except Exception as exc:  # noqa: BLE001 - never kill the monitor
                logger.error("health monitor loop error: %s", exc, exc_info=True)
            self._stop.wait(self._core_interval)

    def start(self) -> None:
        """Start the background monitor thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._loop,
            name="health-monitor",
            daemon=True,
        )
        self._thread.start()
        logger.info("health monitor started (core every %.0fs, ai every %.0fs)", self._core_interval, self._ai_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


def attach_monitor(app) -> HealthMonitor:
    """Create, run the startup check and start the monitor; store on app.extensions."""
    monitor = HealthMonitor(
        app,
        core_interval=float(os.getenv("HEALTH_CHECK_INTERVAL_SECONDS", "60")),
        ai_interval=float(os.getenv("HEALTH_AI_INTERVAL_SECONDS", "300")),
    )
    monitor.run_startup_check()
    # Skip the background thread under test to keep the test process clean.
    if not app.config.get("TESTING"):
        monitor.start()
    app.extensions["health_monitor"] = monitor
    return monitor
