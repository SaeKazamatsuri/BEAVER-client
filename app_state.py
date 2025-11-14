from __future__ import annotations

import queue
import threading
import time
from collections import deque

import socketio
import tkinter as tk


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
