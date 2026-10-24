"""Shared notification history for Better Hyprland (no Qt, no D-Bus: plain Python).

Two processes use it:
    notification-catcher.py   adds notifications (and reads the Do Not Disturb flag)
    notifications.py          the panel: lists them, dismisses them, flips Do Not Disturb

The data lives in one small JSON file, rewritten atomically under a file lock, so neither process
ever sees a half-written file and neither needs the other to be running.

    ~/.local/state/better-hyprland/notifications.json
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path

MAX_ITEMS = 100
FIELDS = ("id", "app_name", "summary", "body", "app_icon", "image_path", "timestamp", "urgency")


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "better-hyprland"


def state_path() -> Path:
    return state_dir() / "notifications.json"


def image_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "better-hyprland" / "notification-images"


def _empty() -> dict:
    return {"next_id": 1, "dnd": False, "items": []}


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            return _empty()
        data.setdefault("next_id", 1)
        data.setdefault("dnd", False)
        return data
    except (OSError, ValueError):
        return _empty()


@contextlib.contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _save(path: Path, data: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".notifications-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.replace(tmp, path)  # atomic: readers see the old file or the new one, never a mix
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read(path: Path | None = None) -> dict:
    """{"dnd": bool, "items": [dict, ...]} with items oldest -> newest."""
    return _load(path or state_path())


def add(item: dict, path: Path | None = None) -> tuple[int, bool]:
    """Store a notification. `item["id"] > 0` replaces that notification. Returns (id, dnd)."""
    path = path or state_path()
    with _locked(path):
        data = _load(path)
        wanted = int(item.get("id") or 0)
        if wanted > 0:
            notification_id = wanted
        else:
            notification_id = int(data["next_id"])
        data["next_id"] = max(int(data["next_id"]), notification_id) + 1
        record = {key: item.get(key, "") for key in FIELDS}
        record["id"] = notification_id
        record["timestamp"] = float(item.get("timestamp") or time.time())
        record["urgency"] = int(item.get("urgency", 1))
        data["items"] = [i for i in data["items"] if i.get("id") != notification_id]
        data["items"].append(record)
        data["items"] = data["items"][-MAX_ITEMS:]
        _save(path, data)
        return notification_id, bool(data["dnd"])


def dismiss(notification_id: int, path: Path | None = None) -> None:
    path = path or state_path()
    with _locked(path):
        data = _load(path)
        kept = [i for i in data["items"] if i.get("id") != notification_id]
        if len(kept) != len(data["items"]):
            data["items"] = kept
            _save(path, data)


def clear(path: Path | None = None) -> None:
    path = path or state_path()
    with _locked(path):
        data = _load(path)
        if data["items"]:
            data["items"] = []
            _save(path, data)


def set_dnd(enabled: bool, path: Path | None = None) -> None:
    path = path or state_path()
    with _locked(path):
        data = _load(path)
        if bool(data["dnd"]) != enabled:
            data["dnd"] = enabled
            _save(path, data)
