import os
import io
import html
import queue
import random
import threading
import time
import uuid
import base64
import math
from collections import deque
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox
import tkinter.ttk as ttk
from tkinterweb import HtmlFrame
from screeninfo import get_monitors
import win32gui
import win32con
import pandas as pd
import socketio
import openpyxl
import requests

BASE_DIR = getattr(__import__("sys"), "_MEIPASS", os.path.abspath("."))
BUBBLE_HTML_PATH = os.path.join(BASE_DIR, "bubble.html")

RELAY_SERVER_URL = os.environ.get("RELAY_SERVER_URL", "https://beaver.works")
RELAY_SOCKETIO_PATH = os.environ.get("RELAY_SOCKETIO_PATH", "/socket.io")

STAMP_BALLOON_LIFETIME_SEC = 8.0
STAMP_BALLOON_MIN_SPEED_PX = 70.0
STAMP_BALLOON_MAX_SPEED_PX = 110.0
STAMP_BALLOON_MAX_ACTIVE = 8
STAMP_BALLOON_MAX_WIDTH = 220
STAMP_BALLOON_START_PADDING = 40
STAMP_BALLOON_WOBBLE_AMPLITUDE = 25.0
STAMP_BALLOON_WOBBLE_FREQ_MIN = 0.6
STAMP_BALLOON_WOBBLE_FREQ_MAX = 1.2
STAMP_RECENT_WINDOW_SEC = 20.0
STAMP_DOWNLOAD_TIMEOUT = 10
OVERLAY_TRANSPARENT_COLOR = "#00ff00"
STAMP_ID_CACHE_SIZE = 128

message_queue = queue.Queue()
message_log: list[dict] = []
messages: list[dict] = []

overlay_window: tk.Toplevel | None = None
overlay_canvas: tk.Canvas | None = None
overlay_balloons: list[dict] = []
_overlay_animating = False
_overlay_last_tick = [time.monotonic()]
_recent_stamp_ids: deque[str] = deque()
_recent_stamp_ids_set: set[str] = set()

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


def _safe_set(var: tk.StringVar | None, text: str):
    if root is None or var is None:
        return
    try:
        root.after(0, lambda: var.set(text))
    except Exception:
        pass


def _update_server_offset(ts_seconds: float | None):
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


def _coerce_ts_seconds(entry: dict) -> float | None:
    ts = entry.get("ts") or entry.get("server_ts")
    if isinstance(ts, (int, float)):
        x = float(ts)
        if x > 1e12:
            return x / 1000.0
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


def _is_stamp(entry: dict) -> bool:
    return bool(entry.get("stamp_url") or entry.get("stamp"))


def _should_drop_on_arrival(entry: dict) -> bool:
    if not _is_stamp(entry):
        return False
    ts = _coerce_ts_seconds(entry)
    if ts is None:
        return False
    _update_server_offset(ts)
    return (server_now_seconds() - ts) >= STAMP_RECENT_WINDOW_SEC


def _annotate_entry(entry: dict) -> dict:
    e = dict(entry)
    ts = _coerce_ts_seconds(e)
    if ts is not None:
        _update_server_offset(ts)
        e["_ts"] = ts
    return e

def _normalize_stamp_src(entry: dict) -> tuple[str, str] | None:
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


def _enqueue_stamp_balloon(entry: dict):
    normalized = _normalize_stamp_src(entry)
    if normalized is None:
        return
    stamp_id, url = normalized
    if stamp_id in _recent_stamp_ids_set:
        return
    _recent_stamp_ids.append(stamp_id)
    _recent_stamp_ids_set.add(stamp_id)
    while len(_recent_stamp_ids) > STAMP_ID_CACHE_SIZE:
        old = _recent_stamp_ids.popleft()
        _recent_stamp_ids_set.discard(old)
    threading.Thread(
        target=_download_and_prepare_stamp, args=(stamp_id, url), daemon=True
    ).start()


def _download_and_prepare_stamp(stamp_id: str, url: str):
    try:
        resp = requests.get(url, timeout=STAMP_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        data = resp.content
    except Exception:
        return
    if not data or root is None:
        return

    def _spawn():
        _spawn_balloon_from_bytes(stamp_id, data)

    try:
        root.after(0, _spawn)
    except Exception:
        pass


def _spawn_balloon_from_bytes(stamp_id: str, data: bytes):
    if root is None:
        return
    _ensure_overlay_window(root)
    if overlay_canvas is None:
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

    overlay_canvas.update_idletasks()
    canvas_w = overlay_canvas.winfo_width() or root.winfo_width()
    canvas_h = overlay_canvas.winfo_height() or root.winfo_height()
    if canvas_w <= 0 or canvas_h <= 0:
        root.after(120, lambda: _spawn_balloon_from_bytes(stamp_id, data))
        return

    half_w = photo.width() / 2
    min_x = STAMP_BALLOON_START_PADDING + half_w
    max_x = max(min_x + 1, canvas_w - min_x)
    spawn_x = random.uniform(min_x, max_x)
    spawn_y = canvas_h + photo.height() / 2 + 12

    canvas_id = overlay_canvas.create_image(
        spawn_x, spawn_y, image=photo, anchor="center"
    )
    balloon = {
        "stamp_id": stamp_id,
        "canvas_id": canvas_id,
        "photo": photo,
        "vx": random.uniform(-20.0, 20.0),
        "vy": -random.uniform(STAMP_BALLOON_MIN_SPEED_PX, STAMP_BALLOON_MAX_SPEED_PX),
        "start": time.monotonic(),
        "life": STAMP_BALLOON_LIFETIME_SEC,
        "phase": random.uniform(0.0, math.tau),
        "wobble": random.uniform(5.0, STAMP_BALLOON_WOBBLE_AMPLITUDE),
        "freq": random.uniform(
            STAMP_BALLOON_WOBBLE_FREQ_MIN, STAMP_BALLOON_WOBBLE_FREQ_MAX
        ),
    }
    overlay_balloons.append(balloon)
    while len(overlay_balloons) > STAMP_BALLOON_MAX_ACTIVE:
        old = overlay_balloons.pop(0)
        try:
            overlay_canvas.delete(old["canvas_id"])
        except Exception:
            pass


def _ensure_overlay_window(root_ref: tk.Tk):
    global overlay_window, overlay_canvas, _overlay_animating
    if overlay_window is not None and overlay_canvas is not None:
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
    overlay_window = overlay
    overlay_canvas = canvas
    _overlay_animating = True
    _overlay_last_tick[0] = time.monotonic()
    canvas.after(16, _overlay_tick)


def _update_overlay_geometry(geometry: str, width: int, height: int):
    if overlay_window is None or overlay_canvas is None:
        return
    overlay_window.geometry(geometry)
    overlay_canvas.config(width=width, height=height)


def _overlay_tick():
    if not _overlay_animating or overlay_canvas is None:
        return
    now = time.monotonic()
    last = _overlay_last_tick[0]
    dt = max(0.0, min(0.05, now - last))
    _overlay_last_tick[0] = now

    to_remove: list[dict] = []
    for balloon in list(overlay_balloons):
        balloon["phase"] += dt
        wobble = math.sin(balloon["phase"] * balloon["freq"]) * balloon["wobble"]
        dx = (balloon["vx"] + wobble) * dt
        dy = balloon["vy"] * dt
        overlay_canvas.move(balloon["canvas_id"], dx, dy)
        coords = overlay_canvas.coords(balloon["canvas_id"])
        elapsed = now - balloon["start"]
        if (
            not coords
            or elapsed >= balloon["life"]
            or coords[1] < -balloon["photo"].height()
        ):
            to_remove.append(balloon)

    for balloon in to_remove:
        try:
            overlay_canvas.delete(balloon["canvas_id"])
        except Exception:
            pass
        try:
            overlay_balloons.remove(balloon)
        except ValueError:
            pass

    if _overlay_animating and overlay_canvas is not None:
        overlay_canvas.after(16, _overlay_tick)


def _on_history(data):
    if isinstance(data, list):
        filtered = []
        for m in data:
            if not _should_drop_on_arrival(m):
                filtered.append(m)
        message_log.clear()
        message_log.extend(filtered)
        while True:
            try:
                message_queue.get_nowait()
            except queue.Empty:
                break
        for m in filtered:
            message_queue.put(m)


def _on_new_comment(entry):
    if isinstance(entry, dict):
        if _should_drop_on_arrival(entry):
            return
        message_log.append(entry)
        message_queue.put(entry)


@sio.on("history")
def history_handler(data):
    _on_history(data)


@sio.on("new_comment")
def new_comment_handler(data):
    _on_new_comment(data)


@sio.on("connect")
def on_connect():
    _safe_set(menu_status_var, "接続済み")
    _safe_set(menu_current_session_var, f"現在のセッション: {CURRENT_SESSION}")


@sio.on("disconnect")
def on_disconnect():
    _safe_set(menu_status_var, "未接続")


def connect_session(session_name: str):
    def _do_connect():
        global CURRENT_SESSION
        _safe_set(menu_status_var, "接続中…")
        try:
            if sio.connected:
                try:
                    sio.disconnect()
                except Exception:
                    pass
            CURRENT_SESSION = session_name or "default"
            messages.clear()
            while True:
                try:
                    message_queue.get_nowait()
                except queue.Empty:
                    break
            url = f"{RELAY_SERVER_URL}?session={CURRENT_SESSION}"
            sio.connect(url, socketio_path=RELAY_SOCKETIO_PATH)
            _safe_set(menu_status_var, "接続済み")
            _safe_set(menu_current_session_var, f"現在のセッション: {CURRENT_SESSION}")
        except Exception as e:
            _safe_set(menu_status_var, "接続失敗")
            try:
                messagebox.showerror("接続エラー", str(e))
            except Exception:
                pass

    threading.Thread(target=_do_connect, daemon=True).start()


def set_always_on_top(hwnd):
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
    )


def _open_history_window(root_ref: tk.Tk):
    win = tk.Toplevel(root_ref)
    win.title("コメント履歴")
    win.geometry("560x600")

    frame = ttk.Frame(win)
    frame.pack(expand=True, fill="both")

    columns = ("time", "name", "content")
    tree = ttk.Treeview(frame, columns=columns, show="headings")
    tree.heading("time", text="時刻")
    tree.heading("name", text="名前")
    tree.heading("content", text="内容")
    tree.column("time", width=120, anchor="w")
    tree.column("name", width=120, anchor="w")
    tree.column("content", width=300, anchor="w")

    vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=vsb.set)
    tree.pack(side="left", expand=True, fill="both")
    vsb.pack(side="right", fill="y")

    last_count = [-1]

    def make_row(e: dict) -> tuple[str, str, str]:
        t = str(e.get("time", "")) if e.get("time") is not None else ""
        n = str(e.get("name", "")) if e.get("name") is not None else ""
        if e.get("stamp_url") or e.get("stamp"):
            s = e.get("stamp_url") or e.get("stamp")
            c = f"スタンプ: {s}"
        else:
            c = str(e.get("text", "")) if e.get("text") is not None else ""
        return (t, n, c)

    def refresh():
        if not win.winfo_exists():
            return
        current_len = len(message_log)
        if current_len != last_count[0]:
            tree.delete(*tree.get_children())
            snapshot = list(message_log)
            for e in snapshot:
                tree.insert("", "end", values=make_row(e))
            last_count[0] = current_len
        win.after(500, refresh)

    refresh()


def create_menu_window(switch_display_callback, root_ref: tk.Tk):
    global menu_status_var, menu_session_var, menu_current_session_var
    menu = tk.Toplevel()
    menu.title("コントロールメニュー")
    menu.geometry("350x420")
    menu.attributes("-topmost", True)

    menu_status_var = tk.StringVar(value="未接続")
    menu_current_session_var = tk.StringVar(value="現在のセッション: なし")
    menu_session_var = tk.StringVar(value="default")

    tk.Label(menu, textvariable=menu_status_var).pack(pady=(10, 5))
    tk.Label(menu, textvariable=menu_current_session_var).pack(pady=(0, 10))

    frame = tk.Frame(menu)
    frame.pack(pady=5, fill="x", padx=10)
    tk.Label(frame, text="セッションID").grid(row=0, column=0, sticky="w")
    entry = tk.Entry(frame, textvariable=menu_session_var, width=28)
    entry.grid(row=1, column=0, padx=(0, 8), pady=(2, 0), sticky="w")
    tk.Button(
        frame,
        text="接続",
        command=lambda: connect_session(menu_session_var.get().strip()),
    ).grid(row=1, column=1, sticky="e")

    def export_dialog(fmt: str):
        if not message_log:
            messagebox.showinfo("保存", "データがありません")
            return
        df = pd.DataFrame(message_log).rename(
            columns={
                "real_name": "本名",
                "name": "名前",
                "text": "コメント",
                "time": "時刻",
            }
        )
        if fmt == "xlsx":
            path = filedialog.asksaveasfilename(
                defaultextension=".xlsx", filetypes=[("Excelファイル", "*.xlsx")]
            )
            if not path:
                return
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                df.to_excel(writer, index=False, sheet_name="コメント履歴")
            with open(path, "wb") as f:
                f.write(out.getvalue())
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".csv", filetypes=[("CSVファイル", "*.csv")]
            )
            if not path:
                return
            df.to_csv(path, index=False, encoding="utf-8-sig")
        messagebox.showinfo("保存", "保存しました")

    def confirm_exit():
        try:
            if sio.connected:
                sio.disconnect()
        except Exception:
            pass
        root_ref.destroy()

    tk.Button(menu, text="表示モニター切替", command=switch_display_callback).pack(
        pady=8
    )
    tk.Button(
        menu, text="コメント履歴", command=lambda: _open_history_window(root_ref)
    ).pack(pady=5)
    tk.Button(menu, text="CSV で保存", command=lambda: export_dialog("csv")).pack(
        pady=5
    )
    tk.Button(menu, text="Excel で保存", command=lambda: export_dialog("xlsx")).pack(
        pady=5
    )
    tk.Button(menu, text="アプリ終了", command=confirm_exit).pack(pady=12)


def main():
    global root
    root = tk.Tk()
    root.title("コメント表示")
    root.overrideredirect(True)

    monitors = get_monitors()
    current_monitor = [0]

    def update_monitor_position():
        scr = monitors[current_monitor[0]]
        w, h = scr.width // 4, scr.height
        geometry = f"{w}x{h}+{scr.x + scr.width - w}+{scr.y}"
        root.geometry(geometry)
        root.resizable(False, True)
        _update_overlay_geometry(geometry, w, h)

    update_monitor_position()
    root.configure(bg="#fefefe")
    root.attributes("-topmost", True)
    root.update()
    set_always_on_top(root.winfo_id())
    _ensure_overlay_window(root)
    _update_overlay_geometry(root.winfo_geometry(), root.winfo_width(), root.winfo_height())

    wrapper = tk.Frame(root, bg="#fefefe")
    wrapper.pack(expand=True, fill="both")

    html_frame = HtmlFrame(
        wrapper, horizontal_scrollbar=False, vertical_scrollbar=False
    )
    html_frame.pack(expand=True, fill="both")

    for child in html_frame.winfo_children():
        if child.winfo_class() == "Scrollbar":
            child.pack_forget()

    with open(BUBBLE_HTML_PATH, encoding="utf-8") as fp:
        bubble_html = fp.read()

    last_html = [""]

    style_block = """
<style>
html, body {
  margin: 0;
  padding: 0;
  height: 100%;
  width: 100%;
  overflow: hidden;
  font-family: "Noto Sans JP", sans-serif;
  background-color: #6dd3f7;
}
#app-root {
  position: relative;
  width: 100%;
  height: 100vh;
  overflow: hidden;
  background-color: #6dd3f7;
}
#comment-column {
  position: relative;
  height: 100%;
  overflow-y: auto;
  padding: 28px 20px 40px 20px;
  box-sizing: border-box;
}
#comment-column::-webkit-scrollbar {
  width: 0;
  height: 0;
}
.comment-wrapper {
  position: relative;
  max-width: 92%;
  margin: 0 auto 24px auto;
}
.comment-wrapper:last-child {
  margin-bottom: 0;
}
.shadow-box {
  background-color: #2c3d52;
  width: 100%;
  height: 100%;
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 0;
  border: 2px solid #0b1f33;
}
.comment-box {
  background-color: #ffffff;
  border: 2px solid #0b1f33;
  padding: 20px;
  position: relative;
  z-index: 1;
  box-shadow: 0 8px 16px rgba(11, 31, 51, 0.18);
}
.name-label {
  position: absolute;
  top: -18px;
  left: -8px;
  background-color: #ffffff;
  border: 2px solid #0b1f33;
  padding: 6px 20px;
  font-weight: bold;
  box-shadow: 2px 2px 0px rgba(11, 31, 51, 0.7);
}
.comment-name-time {
  text-align: right;
  font-weight: bold;
  color: #555555;
  margin-bottom: 8px;
}
.comment-text {
  font-size: 20px;
  line-height: 1.6;
  font-weight: 400;
  color: #222222;
}
.like {
  margin-top: 8px;
  min-height: 12px;
}
</style>
""".strip()

    if "</head>" in bubble_html:
        base_html = bubble_html.replace("</head>", f"{style_block}</head>")
    elif "<body" in bubble_html:
        base_html = bubble_html.replace("<body>", f"<body>{style_block}")
    else:
        base_html = style_block + bubble_html

    comment_placeholder = "<!--COMMENT_COLUMN-->"


    def update_comments():
        try:
            while True:
                raw = message_queue.get_nowait()
                e = _annotate_entry(raw)
                if _is_stamp(e):
                    _enqueue_stamp_balloon(e)
                    continue
                messages.append(e)
        except queue.Empty:
            pass

        comment_items = []
        for m in reversed(messages):
            name = html.escape(m.get("name", ""))
            tstr = html.escape(str(m.get("time", "")))
            time_part = f"<span style='font-weight:normal;color:#666;'>{tstr}</span>"
            text_html = html.escape(m.get("text", ""))
            item = f"""
            <div class="comment-wrapper">
              <div class="shadow-box"></div>
              <div class="comment-box">
                <div class="name-label">{name}</div>
                <div class="comment-name-time">{time_part}</div>
                <div class="comment-text">{text_html}</div>
                <div class="like"></div>
              </div>
            </div>
            """
            comment_items.append(item)

        comment_html = "\n".join(comment_items)

        full_html = base_html
        if comment_placeholder in full_html:
            full_html = full_html.replace(comment_placeholder, comment_html, 1)
        else:
            full_html = full_html.replace("</body>", f"{comment_html}</body>")
        if full_html != last_html[0]:
            try:
                html_frame.load_html(full_html)
                last_html[0] = full_html
            except Exception:
                pass
        root.after(500, update_comments)

    def switch_display():
        current_monitor[0] = (current_monitor[0] + 1) % len(monitors)
        update_monitor_position()

    create_menu_window(switch_display, root)
    update_comments()

    def on_close():
        global overlay_window, overlay_canvas, _overlay_animating
        try:
            if sio.connected:
                sio.disconnect()
        except Exception:
            pass
        _overlay_animating = False
        overlay_balloons.clear()
        if overlay_window is not None:
            try:
                overlay_window.destroy()
            except Exception:
                pass
            overlay_window = None
            overlay_canvas = None
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
