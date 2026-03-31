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

from config.constants import (
    BACKEND_BASE_URL,
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
from state import app_state as state
from ui.display_layout import WindowRect


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
        src = BACKEND_BASE_URL.rstrip("/") + src
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
    canvas_w = canvas.winfo_width()
    canvas_h = canvas.winfo_height()
    if canvas_w <= 0 or canvas_h <= 0:
        root = state.root
        if root is not None:
            root.after(120, lambda: _spawn_balloon_from_bytes(stamp_id, data))
        return

    origin_x, origin_y = _canvas_view_origin(canvas)

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
    min_x = origin_x + STAMP_BALLOON_START_PADDING + half_w
    max_x = max(min_x + 1.0, origin_x + canvas_w - STAMP_BALLOON_START_PADDING - half_w)
    spawn_x = random.uniform(min_x, max_x)

    y_off = photo.height() / 2 + 12
    spawn_y = origin_y + canvas_h + y_off

    canvas_id = canvas.create_image(
        spawn_x,
        spawn_y,
        image=photo,
        anchor="center",
        tags=("overlay_balloon",),
    )
    life = getattr(state, "stamp_lifetime_sec", STAMP_BALLOON_LIFETIME_SEC)
    try:
        life = float(life)
    except Exception:
        life = STAMP_BALLOON_LIFETIME_SEC
    life = max(0.1, life)

    canvas_mid_x = origin_x + (canvas_w / 2.0)
    horizontal_sign = 1.0 if spawn_x < canvas_mid_x else -1.0
    vx = random.uniform(-0.15 * speed, 0.15 * speed) + (
        horizontal_sign * random.uniform(0.05 * speed, 0.25 * speed)
    )
    vy = -speed
    balloon = {
        "stamp_id": stamp_id,
        "canvas_id": canvas_id,
        "photo": photo,
        "vx": vx,
        "vy": vy,
        "x": spawn_x,
        "y": spawn_y,
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
    _schedule_force_hide(canvas, canvas_id, life)
    while len(state.overlay_balloons) > STAMP_BALLOON_MAX_ACTIVE:
        old = state.overlay_balloons.pop(0)
        try:
            canvas.delete(old["canvas_id"])
        except Exception:
            pass


def _schedule_force_hide(canvas: tk.Canvas, canvas_id: int, seconds: float) -> None:
    if canvas_id is None:
        return
    try:
        ms = int(max(0.0, float(seconds)) * 1000)
    except Exception:
        return
    if ms <= 0:
        return

    def _cb() -> None:
        _force_remove_balloon(canvas_id)

    try:
        canvas.after(ms, _cb)
    except Exception:
        pass


def _force_remove_balloon(canvas_id: int) -> None:
    canvas = state.overlay_canvas
    if canvas is not None:
        try:
            canvas.delete(canvas_id)
        except Exception:
            pass
    for balloon in list(state.overlay_balloons):
        if balloon.get("canvas_id") == canvas_id:
            try:
                state.overlay_balloons.remove(balloon)
            except ValueError:
                pass
            break


def bind_overlay_canvas(canvas: tk.Canvas) -> None:
    state.overlay_canvas = canvas
    state.overlay_window = None
    if state.overlay_animating:
        return
    state.overlay_animating = True
    state.overlay_last_tick[0] = time.monotonic()
    canvas.after(16, _overlay_tick)


def ensure_overlay_window(_root_ref: tk.Tk) -> None:
    if state.overlay_canvas is None:
        return
    if not state.overlay_animating:
        bind_overlay_canvas(state.overlay_canvas)


def update_overlay_geometry(rect: WindowRect) -> None:
    if state.overlay_canvas is None:
        return
    state.overlay_canvas.config(width=rect.width, height=rect.height)


def _canvas_view_origin(canvas: tk.Canvas) -> Tuple[float, float]:
    try:
        origin_x = float(canvas.canvasx(0))
    except Exception:
        origin_x = 0.0
    try:
        origin_y = float(canvas.canvasy(0))
    except Exception:
        origin_y = 0.0
    return origin_x, origin_y


def _overlay_tick() -> None:
    if not state.overlay_animating or state.overlay_canvas is None:
        return
    now = time.monotonic()
    state.overlay_last_tick[0] = now

    to_remove: list[dict] = []
    canvas = state.overlay_canvas
    canvas_w = canvas.winfo_width()
    canvas_h = canvas.winfo_height()
    origin_x, origin_y = _canvas_view_origin(canvas)
    distance_limit_percent = getattr(state, "stamp_distance_limit_percent", 0.0)
    try:
        distance_limit_percent = float(distance_limit_percent)
    except Exception:
        distance_limit_percent = 0.0
    distance_limit_percent = max(0.0, distance_limit_percent)
    distance_limit_px = 0.0
    if distance_limit_percent > 0.0:
        distance_limit_px = (canvas_h * distance_limit_percent) / 100.0
    for balloon in list(state.overlay_balloons):
        elapsed = now - balloon["start"]
        x = balloon["start_x"] + (balloon["vx"] * elapsed)
        x += math.sin((elapsed * balloon["freq"]) + balloon["phase"]) * balloon["wobble"]
        y = balloon["start_y"] + (balloon["vy"] * elapsed)
        balloon["x"] = x
        balloon["y"] = y
        try:
            canvas.coords(balloon["canvas_id"], x, y)
        except Exception:
            to_remove.append(balloon)
            continue
        if (
            elapsed >= balloon["life"]
            or (
                distance_limit_px > 0.0
                and abs(y - balloon.get("start_y", y))
                >= distance_limit_px
            )
            or x < origin_x - balloon["photo"].width()
            or x > origin_x + canvas_w + balloon["photo"].width()
            or y < origin_y - balloon["photo"].height()
            or y > origin_y + canvas_h + balloon["photo"].height()
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
    canvas = state.overlay_canvas
    if canvas is not None:
        for balloon in list(state.overlay_balloons):
            canvas_id = balloon.get("canvas_id")
            if isinstance(canvas_id, int):
                try:
                    canvas.delete(canvas_id)
                except Exception:
                    pass
    state.overlay_balloons.clear()
    state.overlay_window = None
    state.overlay_canvas = None
