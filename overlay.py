from __future__ import annotations

import base64
import math
import random
import threading
import time
import uuid
from datetime import datetime
from typing import Tuple

import requests
import tkinter as tk

import app_state as state
from constants import (
    OVERLAY_TRANSPARENT_COLOR,
    RELAY_SERVER_URL,
    STAMP_BALLOON_LIFETIME_SEC,
    STAMP_BALLOON_MAX_ACTIVE,
    STAMP_BALLOON_MAX_SPEED_PX,
    STAMP_BALLOON_MAX_WIDTH,
    STAMP_BALLOON_MIN_SPEED_PX,
    STAMP_BALLOON_START_PADDING,
    STAMP_BALLOON_WOBBLE_AMPLITUDE,
    STAMP_BALLOON_WOBBLE_FREQ_MAX,
    STAMP_BALLOON_WOBBLE_FREQ_MIN,
    STAMP_DOWNLOAD_TIMEOUT,
    STAMP_ID_CACHE_SIZE,
    STAMP_RECENT_WINDOW_SEC,
)


def coerce_ts_seconds(entry: dict) -> float | None:
    ts = entry.get("ts") or entry.get("server_ts")
    if isinstance(ts, (int, float)):
        x = float(ts)
        if x > 1e10:
            return x / 1000.0
        return x
    tiso = (
        entry.get("time_iso")
        or entry.get("server_time_iso")
        or entry.get("server_time")
    )
    if isinstance(tiso, str):
        try:
            s = tiso.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s)
            if dt.tzinfo:
                return dt.timestamp()
        except Exception:
            pass
    return None


def is_stamp(entry: dict) -> bool:
    return bool(entry.get("stamp_url") or entry.get("stamp"))


def should_drop_on_arrival(entry: dict) -> bool:
    if not is_stamp(entry):
        return False
    ts = coerce_ts_seconds(entry)
    if ts is None:
        return False
    state.update_server_offset(ts)
    return (state.server_now_seconds() - ts) >= STAMP_RECENT_WINDOW_SEC


def annotate_entry(entry: dict) -> dict:
    result = dict(entry)
    ts = coerce_ts_seconds(result)
    if ts is not None:
        state.update_server_offset(ts)
        result["_ts"] = ts
    return result


def _normalize_stamp_src(entry: dict) -> Tuple[str, str] | None:
    stamp_rel = entry.get("stamp_url") or entry.get("stamp")
    if not stamp_rel:
        return None
    src = stamp_rel
    if isinstance(src, str) and src.startswith("/"):
        src = RELAY_SERVER_URL.rstrip("/") + src
    stamp_id = str(
        entry.get("id") or entry.get("_id") or entry.get("stamp_id") or uuid.uuid4().hex
    )
    return stamp_id, src


def enqueue_stamp_balloon(entry: dict) -> None:
    normalized = _normalize_stamp_src(entry)
    if normalized is None:
        return
    stamp_id, url = normalized
    if stamp_id in state.recent_stamp_ids_set:
        return
    state.recent_stamp_ids.append(stamp_id)
    state.recent_stamp_ids_set.add(stamp_id)
    while len(state.recent_stamp_ids) > STAMP_ID_CACHE_SIZE:
        old = state.recent_stamp_ids.popleft()
        state.recent_stamp_ids_set.discard(old)
    threading.Thread(
        target=_download_and_prepare_stamp, args=(stamp_id, url), daemon=True
    ).start()


def _download_and_prepare_stamp(stamp_id: str, url: str) -> None:
    try:
        resp = requests.get(url, timeout=STAMP_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        data = resp.content
    except Exception:
        return
    if not data or state.root is None:
        return

    def _spawn():
        _spawn_balloon_from_bytes(stamp_id, data)

    try:
        state.root.after(0, _spawn)
    except Exception:
        pass


def _spawn_balloon_from_bytes(stamp_id: str, data: bytes) -> None:
    root = state.root
    if root is None:
        return
    ensure_overlay_window(root)
    canvas = state.overlay_canvas
    if canvas is None:
        return
    try:
        encoded = base64.b64encode(data).decode("ascii")
        photo = tk.PhotoImage(data=encoded)
    except Exception:
        return

    width = photo.width()
    if width <= 0:
        return
    if width > STAMP_BALLOON_MAX_WIDTH:
        factor = max(1, math.ceil(width / STAMP_BALLOON_MAX_WIDTH))
        try:
            photo = photo.subsample(factor, factor)
        except Exception:
            pass

    canvas.update_idletasks()
    canvas_w = canvas.winfo_width() or root.winfo_width()
    canvas_h = canvas.winfo_height() or root.winfo_height()
    if canvas_w <= 0 or canvas_h <= 0:
        root.after(120, lambda: _spawn_balloon_from_bytes(stamp_id, data))
        return

    corner = getattr(state, "stamp_origin_corner", "bottom_right")
    valid_corners = getattr(
        state,
        "STAMP_ORIGIN_CORNERS",
        ("bottom_right", "top_right", "bottom_left", "top_left"),
    )
    if corner not in valid_corners:
        corner = "bottom_right"
    is_left = "left" in corner
    is_top = corner.startswith("top")

    speed_min = getattr(state, "stamp_speed_min_px_s", STAMP_BALLOON_MIN_SPEED_PX)
    speed_max = getattr(state, "stamp_speed_max_px_s", STAMP_BALLOON_MAX_SPEED_PX)
    try:
        speed_min = float(speed_min)
        speed_max = float(speed_max)
    except Exception:
        speed_min = STAMP_BALLOON_MIN_SPEED_PX
        speed_max = STAMP_BALLOON_MAX_SPEED_PX
    speed_min = max(1.0, abs(speed_min))
    speed_max = max(1.0, abs(speed_max))
    speed = random.uniform(speed_min, speed_max)

    half_w = photo.width() / 2
    min_x = STAMP_BALLOON_START_PADDING + half_w
    max_x = max(min_x + 1, canvas_w - min_x)
    span = max(1.0, (max_x - min_x) * 0.35)
    if is_left:
        x0, x1 = min_x, min(max_x, min_x + span)
    else:
        x0, x1 = max(min_x, max_x - span), max_x
    spawn_x = random.uniform(x0, x1)

    y_off = photo.height() / 2 + 12
    spawn_y = -y_off if is_top else canvas_h + y_off

    canvas_id = canvas.create_image(spawn_x, spawn_y, image=photo, anchor="center")
    life = getattr(state, "stamp_lifetime_sec", STAMP_BALLOON_LIFETIME_SEC)
    try:
        life = float(life)
    except Exception:
        life = STAMP_BALLOON_LIFETIME_SEC
    life = max(0.1, life)

    horizontal_sign = 1.0 if is_left else -1.0
    vertical_sign = 1.0 if is_top else -1.0
    vx = random.uniform(-0.15 * speed, 0.15 * speed) + (
        horizontal_sign * random.uniform(0.05 * speed, 0.25 * speed)
    )
    vy = vertical_sign * speed
    balloon = {
        "stamp_id": stamp_id,
        "canvas_id": canvas_id,
        "photo": photo,
        "vx": vx,
        "vy": vy,
        "start_x": spawn_x,
        "start_y": spawn_y,
        "start": time.monotonic(),
        "life": life,
        "phase": random.uniform(0.0, math.tau),
        "wobble": random.uniform(5.0, STAMP_BALLOON_WOBBLE_AMPLITUDE),
        "freq": random.uniform(
            STAMP_BALLOON_WOBBLE_FREQ_MIN, STAMP_BALLOON_WOBBLE_FREQ_MAX
        ),
    }
    state.overlay_balloons.append(balloon)
    while len(state.overlay_balloons) > STAMP_BALLOON_MAX_ACTIVE:
        old = state.overlay_balloons.pop(0)
        try:
            canvas.delete(old["canvas_id"])
        except Exception:
            pass


def ensure_overlay_window(root_ref: tk.Tk) -> None:
    if state.overlay_window is not None and state.overlay_canvas is not None:
        return
    overlay = tk.Toplevel(root_ref)
    overlay.overrideredirect(True)
    overlay.configure(bg=OVERLAY_TRANSPARENT_COLOR)
    overlay.attributes("-topmost", True)
    try:
        overlay.attributes("-transparentcolor", OVERLAY_TRANSPARENT_COLOR)
    except tk.TclError:
        pass
    try:
        overlay.wm_attributes("-disabled", True)
    except tk.TclError:
        pass
    canvas = tk.Canvas(
        overlay, bg=OVERLAY_TRANSPARENT_COLOR, highlightthickness=0, bd=0
    )
    canvas.pack(fill="both", expand=True)
    state.overlay_window = overlay
    state.overlay_canvas = canvas
    state.overlay_animating = True
    state.overlay_last_tick[0] = time.monotonic()
    canvas.after(16, _overlay_tick)
    _raise_overlay_window()


def _raise_overlay_window() -> None:
    overlay = state.overlay_window
    if overlay is None:
        return
    try:
        overlay.lift()
    except Exception:
        pass
    try:
        overlay.attributes("-topmost", True)
    except tk.TclError:
        pass


def update_overlay_geometry(geometry: str, width: int, height: int) -> None:
    if state.overlay_window is None or state.overlay_canvas is None:
        return
    state.overlay_window.geometry(geometry)
    state.overlay_canvas.config(width=width, height=height)
    _raise_overlay_window()


def _overlay_tick() -> None:
    if not state.overlay_animating or state.overlay_canvas is None:
        return
    now = time.monotonic()
    last = state.overlay_last_tick[0]
    dt = max(0.0, min(0.05, now - last))
    state.overlay_last_tick[0] = now

    to_remove: list[dict] = []
    canvas = state.overlay_canvas
    canvas_w = canvas.winfo_width()
    canvas_h = canvas.winfo_height()
    for balloon in list(state.overlay_balloons):
        balloon["phase"] += dt
        wobble = math.sin(balloon["phase"] * balloon["freq"]) * balloon["wobble"]
        dx = (balloon["vx"] + wobble) * dt
        dy = balloon["vy"] * dt
        canvas.move(balloon["canvas_id"], dx, dy)
        coords = canvas.coords(balloon["canvas_id"])
        elapsed = now - balloon["start"]
        distance_limit = getattr(state, "stamp_distance_limit_px", 0.0)
        try:
            distance_limit = float(distance_limit)
        except Exception:
            distance_limit = 0.0
        if (
            not coords
            or elapsed >= balloon["life"]
            or (
                distance_limit > 0
                and math.hypot(
                    coords[0] - balloon.get("start_x", coords[0]),
                    coords[1] - balloon.get("start_y", coords[1]),
                )
                >= distance_limit
            )
            or coords[0] < -balloon["photo"].width()
            or coords[0] > canvas_w + balloon["photo"].width()
            or coords[1] < -balloon["photo"].height()
            or coords[1] > canvas_h + balloon["photo"].height()
        ):
            to_remove.append(balloon)

    for balloon in to_remove:
        try:
            canvas.delete(balloon["canvas_id"])
        except Exception:
            pass
        try:
            state.overlay_balloons.remove(balloon)
        except ValueError:
            pass

    if state.overlay_animating and state.overlay_canvas is not None:
        state.overlay_canvas.after(16, _overlay_tick)


def stop_overlay() -> None:
    state.overlay_animating = False
    state.overlay_balloons.clear()
    if state.overlay_window is not None:
        try:
            state.overlay_window.destroy()
        except Exception:
            pass
    state.overlay_window = None
    state.overlay_canvas = None
