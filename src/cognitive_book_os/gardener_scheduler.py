"""Scheduled execution helpers for the Gardener subsystem."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Optional
import time


def parse_interval_seconds(value: str) -> int:
    """Parse interval setting into seconds."""
    normalized = (value or "").strip().lower()
    mapping = {
        "hourly": 60 * 60,
        "daily": 24 * 60 * 60,
        "weekly": 7 * 24 * 60 * 60,
    }
    if normalized in mapping:
        return mapping[normalized]

    # Allow raw second values for local testing.
    try:
        seconds = int(normalized)
    except ValueError as exc:
        raise ValueError(f"Unsupported interval: {value}") from exc

    if seconds <= 0:
        raise ValueError("Interval seconds must be greater than zero.")
    return seconds


def discover_brain_names(brains_dir: str | Path) -> list[str]:
    """List valid brain names from the brains directory."""
    root = Path(brains_dir)
    if not root.exists():
        return []

    names: list[str] = []
    for item in root.iterdir():
        if not item.is_dir():
            continue
        if (item / "_index.md").exists():
            names.append(item.name)
    return sorted(names)


@dataclass
class SchedulerStatus:
    """Snapshot of scheduler state."""

    running: bool
    started_at: Optional[str]
    last_run_at: Optional[str]
    next_run_at: Optional[str]
    last_run_id: Optional[str]
    last_error: Optional[str]
    interval_seconds: int


class GardenerScheduler:
    """In-process interval loop for scheduled Gardener runs."""

    def __init__(self, interval_seconds: int, run_callback: Callable[[], Optional[str]]):
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self._run_callback = run_callback
        self._stop_event = Event()
        self._thread: Optional[Thread] = None
        self._lock = Lock()
        self._started_at: Optional[str] = None
        self._last_run_at: Optional[str] = None
        self._next_run_at: Optional[str] = None
        self._last_run_id: Optional[str] = None
        self._last_error: Optional[str] = None

    def start(self) -> None:
        """Start scheduler loop if not already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._started_at = datetime.now().isoformat()
            self._next_run_at = (datetime.now() + timedelta(seconds=self.interval_seconds)).isoformat()
            self._thread = Thread(target=self._loop, name="gardener-scheduler", daemon=True)
            self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """Stop scheduler loop."""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread:
            thread.join(timeout=timeout_seconds)
        with self._lock:
            self._thread = None
            self._next_run_at = None

    def is_running(self) -> bool:
        """Check whether scheduler thread is alive."""
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def get_status(self) -> SchedulerStatus:
        """Get an immutable scheduler state snapshot."""
        with self._lock:
            return SchedulerStatus(
                running=bool(self._thread and self._thread.is_alive()),
                started_at=self._started_at,
                last_run_at=self._last_run_at,
                next_run_at=self._next_run_at,
                last_run_id=self._last_run_id,
                last_error=self._last_error,
                interval_seconds=self.interval_seconds,
            )

    def _loop(self) -> None:
        """Background interval loop that invokes callback periodically."""
        while not self._stop_event.is_set():
            # Keep wait resolution short so stop() is responsive.
            if self._stop_event.wait(timeout=1.0):
                break

            now = datetime.now()
            with self._lock:
                next_run_at_raw = self._next_run_at
            if not next_run_at_raw:
                continue

            try:
                next_run_at = datetime.fromisoformat(next_run_at_raw)
            except ValueError:
                with self._lock:
                    self._next_run_at = (now + timedelta(seconds=self.interval_seconds)).isoformat()
                continue

            if now < next_run_at:
                continue

            try:
                run_id = self._run_callback()
                with self._lock:
                    self._last_run_id = run_id
                    self._last_run_at = datetime.now().isoformat()
                    self._last_error = None
            except Exception as exc:  # pragma: no cover - defensive runtime guard
                with self._lock:
                    self._last_error = str(exc)
                    self._last_run_at = datetime.now().isoformat()
            finally:
                with self._lock:
                    self._next_run_at = (
                        datetime.now() + timedelta(seconds=self.interval_seconds)
                    ).isoformat()

            # Yield CPU briefly after each run trigger.
            time.sleep(0.05)
