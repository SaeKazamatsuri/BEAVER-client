from __future__ import annotations

import dataclasses
import queue
import threading
import time
from collections import deque

import tkinter as tk

from config.constants import (
    STAMP_BALLOON_LIFETIME_SEC,
    STAMP_BALLOON_MAX_SPEED_PX,
    STAMP_BALLOON_MIN_SPEED_PX,
)
from ui.comment_ui import CommentEntry

message_queue: queue.Queue[dict[str, object]] = queue.Queue()
behavior_event_queue: queue.Queue[dict[str, object]] = queue.Queue()
message_log: list[dict[str, object]] = []
behavior_event_log: list[dict[str, object]] = []
messages: list[CommentEntry] = []
_message_lock = threading.Lock()
_message_generation = 0
_behavior_event_lock = threading.Lock()
_behavior_event_generation = 0

overlay_window: tk.Toplevel | None = None
overlay_canvas: tk.Canvas | None = None
overlay_balloons: list[dict[str, object]] = []
overlay_animating = False
overlay_last_tick = [time.monotonic()]
recent_stamp_ids: deque[str] = deque()
recent_stamp_ids_set: set[str] = set()

CURRENT_SESSION = "default"
session_ready = False
# コメント表示順: "chronological"（新着順）/ "bookmark"（しおり降順）
display_order: str = "chronological"
root: tk.Tk | None = None
menu_status_var: tk.StringVar | None = None
menu_session_var: tk.StringVar | None = None
menu_current_session_var: tk.StringVar | None = None
experiment_window: tk.Toplevel | None = None
poll_window: tk.Toplevel | None = None
poll_results_window: tk.Toplevel | None = None
poll_results_overlay_window: tk.Toplevel | None = None
visible_poll_results: dict[str, object] | None = None
_poll_results_lock = threading.Lock()
_poll_results_generation = 0
reaction_mode: str = "single_thumb"
reaction_types: list[dict[str, str]] = [
    {"key": "like", "label": "いいね", "emoji": "👍"},
]
_reaction_mode_lock = threading.Lock()
_reaction_mode_generation = 0

# --- Experiment (stamp) settings ---
# These values are intentionally mutable so experiments can tweak them at runtime.
STAMP_AREA_MODES = ("comment",)
STAMP_ORIGIN_CORNERS = ("bottom_right",)

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


def apply_reaction_update(comment_id: int, bookmark_count: int) -> None:
    """注目度のライブ更新。変化があれば世代を進めて再描画させる。"""
    global _message_generation
    with _message_lock:
        changed = False
        for index, entry in enumerate(messages):
            if entry.id == comment_id:
                if entry.bookmark_count != bookmark_count:
                    messages[index] = dataclasses.replace(
                        entry, bookmark_count=bookmark_count
                    )
                    changed = True
                break
        for raw in message_log:
            if raw.get("id") == comment_id:
                if raw.get("bookmark_count") != bookmark_count:
                    raw["bookmark_count"] = bookmark_count
                    changed = True
                break
        if changed:
            _message_generation += 1


def set_reaction_mode(mode: str, reaction_type_items: list[dict[str, object]]) -> None:
    global reaction_mode
    global reaction_types
    global _reaction_mode_generation
    normalized_types: list[dict[str, str]] = []
    for item in reaction_type_items:
        key = item.get("key")
        label = item.get("label")
        emoji = item.get("emoji")
        if isinstance(key, str) and isinstance(label, str) and isinstance(emoji, str):
            normalized_types.append({"key": key, "label": label, "emoji": emoji})
    if not normalized_types:
        normalized_types = [{"key": "like", "label": "いいね", "emoji": "👍"}]
    with _reaction_mode_lock:
        reaction_mode = mode
        reaction_types = normalized_types
        _reaction_mode_generation += 1


def snapshot_reaction_mode() -> tuple[int, str, list[dict[str, str]]]:
    with _reaction_mode_lock:
        return _reaction_mode_generation, reaction_mode, [dict(item) for item in reaction_types]


def set_behavior_events(events: list[dict[str, object]]) -> None:
    global _behavior_event_generation
    with _behavior_event_lock:
        behavior_event_log.clear()
        behavior_event_log.extend(dict(event) for event in events)
        _behavior_event_generation += 1


def append_behavior_event(event: dict[str, object]) -> None:
    global _behavior_event_generation
    with _behavior_event_lock:
        behavior_event_log.insert(0, dict(event))
        del behavior_event_log[500:]
        _behavior_event_generation += 1
    behavior_event_queue.put(dict(event))


def snapshot_behavior_events() -> tuple[int, list[dict[str, object]]]:
    with _behavior_event_lock:
        return _behavior_event_generation, [dict(event) for event in behavior_event_log]


def set_visible_poll_results(results: dict[str, object] | None) -> None:
    global visible_poll_results
    global _poll_results_generation
    with _poll_results_lock:
        visible_poll_results = dict(results) if results is not None else None
        _poll_results_generation += 1


def snapshot_visible_poll_results() -> tuple[int, dict[str, object] | None]:
    with _poll_results_lock:
        result = dict(visible_poll_results) if visible_poll_results is not None else None
        return _poll_results_generation, result


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


