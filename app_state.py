from __future__ import annotations

import queue
import threading
import time
from collections import deque
from typing import Callable

import socketio
import tkinter as tk

from constants import (
    STAMP_BALLOON_LIFETIME_SEC,
    STAMP_BALLOON_MAX_SPEED_PX,
    STAMP_BALLOON_MIN_SPEED_PX,
)

message_queue: queue.Queue = queue.Queue()
message_log: list[dict] = []
messages: list[dict] = []

overlay_window: tk.Toplevel | None = None
overlay_canvas: tk.Canvas | None = None
overlay_balloons: list[dict] = []
overlay_animating = False
overlay_last_tick = [time.monotonic()]
recent_stamp_ids: deque[str] = deque()
recent_stamp_ids_set: set[str] = set()

sio = socketio.Client(
    reconnection=True, reconnection_attempts=0, logger=False, engineio_logger=False
)

CURRENT_SESSION = "default"
root: tk.Tk | None = None
menu_status_var: tk.StringVar | None = None
menu_session_var: tk.StringVar | None = None
menu_current_session_var: tk.StringVar | None = None
experiment_window: tk.Toplevel | None = None
request_layout_refresh: Callable[[], None] | None = None

# --- Experiment (stamp) settings ---
# These values are intentionally mutable so experiments can tweak them at runtime.
STAMP_AREA_MODES = ("comment", "left75")
STAMP_ORIGIN_CORNERS = ("bottom_right", "top_right", "bottom_left", "top_left")

stamp_area_mode: str = "comment"
stamp_origin_corner: str = "bottom_right"
stamp_speed_min_px_s: float = STAMP_BALLOON_MIN_SPEED_PX
stamp_speed_max_px_s: float = STAMP_BALLOON_MAX_SPEED_PX
stamp_distance_limit_px: float = 0.0  # 0 = unlimited
stamp_lifetime_sec: float = STAMP_BALLOON_LIFETIME_SEC


def reset_stamp_experiment_settings() -> None:
    global stamp_area_mode
    global stamp_origin_corner
    global stamp_speed_min_px_s
    global stamp_speed_max_px_s
    global stamp_distance_limit_px
    global stamp_lifetime_sec

    stamp_area_mode = "comment"
    stamp_origin_corner = "bottom_right"
    stamp_speed_min_px_s = STAMP_BALLOON_MIN_SPEED_PX
    stamp_speed_max_px_s = STAMP_BALLOON_MAX_SPEED_PX
    stamp_distance_limit_px = 0.0
    stamp_lifetime_sec = STAMP_BALLOON_LIFETIME_SEC

_server_offset_lock = threading.Lock()
_server_offset: float | None = None


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
