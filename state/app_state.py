from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Callable

import tkinter as tk

from config.constants import (
    STAMP_BALLOON_LIFETIME_SEC,
    STAMP_BALLOON_MAX_SPEED_PX,
    STAMP_BALLOON_MIN_SPEED_PX,
)
from ui.comment_ui import CommentEntry

message_queue: queue.Queue[dict[str, object]] = queue.Queue()
message_log: list[dict[str, object]] = []
messages: list[CommentEntry] = []
_message_lock = threading.Lock()
_message_generation = 0

overlay_window: tk.Toplevel | None = None
overlay_canvas: tk.Canvas | None = None
overlay_balloons: list[dict[str, object]] = []
overlay_animating = False
overlay_last_tick = [time.monotonic()]
recent_stamp_ids: deque[str] = deque()
recent_stamp_ids_set: set[str] = set()

CURRENT_SESSION = "default"
session_ready = False
root: tk.Tk | None = None
menu_status_var: tk.StringVar | None = None
menu_session_var: tk.StringVar | None = None
menu_current_session_var: tk.StringVar | None = None
experiment_window: tk.Toplevel | None = None
transcription_history_window: tk.Toplevel | None = None
request_layout_refresh: Callable[[], None] | None = None

# --- Experiment (stamp) settings ---
# These values are intentionally mutable so experiments can tweak them at runtime.
STAMP_AREA_MODES = ("comment", "left75")
STAMP_ORIGIN_CORNERS = ("bottom_right", "bottom_left")

stamp_area_mode: str = "comment"
stamp_origin_corner: str = "bottom_right"
stamp_speed_min_px_s: float = STAMP_BALLOON_MIN_SPEED_PX
stamp_speed_max_px_s: float = STAMP_BALLOON_MAX_SPEED_PX
stamp_distance_limit_percent: float = 0.0  # 0 = unlimited
stamp_lifetime_sec: float = STAMP_BALLOON_LIFETIME_SEC


def reset_stamp_experiment_settings() -> None:
    global stamp_area_mode
    global stamp_origin_corner
    global stamp_speed_min_px_s
    global stamp_speed_max_px_s
    global stamp_distance_limit_percent
    global stamp_lifetime_sec

    stamp_area_mode = "comment"
    stamp_origin_corner = "bottom_right"
    stamp_speed_min_px_s = STAMP_BALLOON_MIN_SPEED_PX
    stamp_speed_max_px_s = STAMP_BALLOON_MAX_SPEED_PX
    stamp_distance_limit_percent = 0.0
    stamp_lifetime_sec = STAMP_BALLOON_LIFETIME_SEC

_server_offset_lock = threading.Lock()
_server_offset: float | None = None
_transcription_lock = threading.Lock()

transcription_items: list[dict[str, object]] = []
transcription_events: list[dict[str, object]] = []
transcription_status: dict[str, object] = {
    "state": "idle",
    "badge": "未接続",
    "process_alive": False,
    "session": "",
    "last_started_at": None,
    "last_success_at": None,
    "last_error_at": None,
    "last_error_message": None,
}


def clear_messages() -> None:
    global _message_generation
    with _message_lock:
        messages.clear()
        _message_generation += 1


def append_message(entry: CommentEntry) -> None:
    with _message_lock:
        messages.append(entry)


def snapshot_messages() -> tuple[int, list[CommentEntry]]:
    with _message_lock:
        return _message_generation, list(messages)


def safe_set(var: tk.StringVar | None, text: str) -> None:
    if root is None or var is None:
        return
    try:
        root.after(0, lambda: var.set(text))
    except Exception:
        pass


def update_server_offset(ts_seconds: float | None) -> None:
    global _server_offset
    if ts_seconds is None:
        return
    with _server_offset_lock:
        _server_offset = ts_seconds - time.monotonic()


def server_now_seconds() -> float:
    with _server_offset_lock:
        if _server_offset is None:
            return time.monotonic()
        return time.monotonic() + _server_offset


def _optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _status_badge(snapshot: dict[str, object]) -> str:
    state_value = str(snapshot.get("state", "idle"))
    session = _optional_string(snapshot.get("session"))
    if state_value == "stopped":
        return "停止"
    if session is None:
        return "未接続"
    if state_value == "starting":
        return "起動中"
    if state_value == "error":
        return "異常"
    if bool(snapshot.get("process_alive", False)):
        if _optional_string(snapshot.get("last_success_at")) is not None:
            return "稼働中"
        return "待機中"
    return "停止"


def set_transcription_session(session: str | None) -> None:
    normalized_session = (session or "").strip()
    with _transcription_lock:
        state_value = str(transcription_status.get("state", "idle"))
        transcription_items.clear()
        transcription_events.clear()
        transcription_status["session"] = normalized_session
        transcription_status["last_success_at"] = None
        if state_value != "error":
            transcription_status["last_error_at"] = None
            transcription_status["last_error_message"] = None
        transcription_status["badge"] = _status_badge(transcription_status)


def replace_transcription_items(items: list[dict[str, object]]) -> None:
    with _transcription_lock:
        current_session = _optional_string(transcription_status.get("session"))
        deduplicated: dict[int, dict[str, object]] = {}
        for item in items:
            item_id = item.get("id")
            session_value = _optional_string(item.get("session"))
            if not isinstance(item_id, int):
                continue
            if current_session is not None and session_value != current_session:
                continue
            deduplicated[item_id] = dict(item)
        transcription_items.clear()
        for key in sorted(deduplicated):
            transcription_items.append(deduplicated[key])


def append_transcription_item(item: dict[str, object]) -> None:
    item_id = item.get("id")
    item_session = _optional_string(item.get("session"))
    if not isinstance(item_id, int):
        return
    with _transcription_lock:
        current_session = _optional_string(transcription_status.get("session"))
        if current_session is not None and item_session != current_session:
            return
        if any(existing.get("id") == item_id for existing in transcription_items):
            return
        transcription_items.append(dict(item))
        transcription_items.sort(key=lambda entry: int(entry.get("id", 0)))


def record_transcription_service_update(
    snapshot: dict[str, object],
    event: dict[str, object] | None,
) -> None:
    with _transcription_lock:
        transcription_status["state"] = str(snapshot.get("state", "idle"))
        transcription_status["process_alive"] = bool(snapshot.get("process_alive", False))
        transcription_status["session"] = str(snapshot.get("session", "") or "")
        transcription_status["last_started_at"] = _optional_string(
            snapshot.get("last_started_at")
        )
        transcription_status["last_success_at"] = _optional_string(
            snapshot.get("last_success_at")
        )
        transcription_status["last_error_at"] = _optional_string(
            snapshot.get("last_error_at")
        )
        transcription_status["last_error_message"] = _optional_string(
            snapshot.get("last_error_message")
        )
        transcription_status["badge"] = _status_badge(transcription_status)

        if event is not None:
            event_copy = dict(event)
            event_copy["session"] = str(event_copy.get("session", "") or "")
            transcription_events.append(event_copy)


def snapshot_transcription_history() -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    with _transcription_lock:
        return (
            dict(transcription_status),
            [dict(item) for item in transcription_items],
            [dict(event) for event in transcription_events],
        )
