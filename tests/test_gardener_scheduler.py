"""Tests for gardener scheduler helpers."""

from pathlib import Path
from threading import Event

from cognitive_book_os.gardener_scheduler import (
    GardenerScheduler,
    discover_brain_names,
    parse_interval_seconds,
)


def test_parse_interval_seconds_supports_named_and_numeric_values():
    assert parse_interval_seconds("hourly") == 3600
    assert parse_interval_seconds("daily") == 86400
    assert parse_interval_seconds("weekly") == 604800
    assert parse_interval_seconds("15") == 15


def test_discover_brain_names_filters_valid_brain_directories(tmp_path: Path):
    valid = tmp_path / "brain-a"
    valid.mkdir(parents=True)
    (valid / "_index.md").write_text("# index", encoding="utf-8")

    invalid = tmp_path / "brain-b"
    invalid.mkdir(parents=True)
    (invalid / "notes.md").write_text("n", encoding="utf-8")

    assert discover_brain_names(tmp_path) == ["brain-a"]


def test_scheduler_invokes_callback_after_interval():
    triggered = Event()

    def _callback():
        triggered.set()
        return "run-1"

    scheduler = GardenerScheduler(interval_seconds=1, run_callback=_callback)
    scheduler.start()
    try:
        assert triggered.wait(timeout=3.0)
        status = scheduler.get_status()
        assert status.running is True
        assert status.last_run_id == "run-1"
    finally:
        scheduler.stop()
