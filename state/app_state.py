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
# コメント表示順: "chronological"（新着順）/ "bookmark"（しおり降順）
display_order: str = "chronological"
root: tk.Tk | None = None
menu_status_var: tk.StringVar | None = None
menu_session_var: tk.StringVar | None = None
menu_current_session_var: tk.StringVar | None = None
experiment_window: tk.Toplevel | None = None
poll_window: tk.Toplevel | None = None
poll_results_window: tk.Toplevel | None = None

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
    """しおり件数のライブ更新。変化があれば世代を進めて再描画させる。"""
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


