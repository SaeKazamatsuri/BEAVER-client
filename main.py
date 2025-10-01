import os
import io
import html
import queue
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinterweb import HtmlFrame
from screeninfo import get_monitors
import win32gui
import win32con
import pandas as pd
import socketio
import openpyxl

BASE_DIR = getattr(__import__("sys"), "_MEIPASS", os.path.abspath("."))
BUBBLE_HTML_PATH = os.path.join(BASE_DIR, "bubble.html")

RELAY_SERVER_URL = os.environ.get("RELAY_SERVER_URL", "https://beaver.works")
RELAY_SOCKETIO_PATH = os.environ.get("RELAY_SOCKETIO_PATH", "/socket.io")

message_queue = queue.Queue()
message_log: list[dict] = []
messages: list[dict] = []

sio = socketio.Client(
    reconnection=True, reconnection_attempts=0, logger=False, engineio_logger=False
)

CURRENT_SESSION = "default"
root: tk.Tk | None = None
menu_status_var: tk.StringVar | None = None
menu_session_var: tk.StringVar | None = None
menu_current_session_var: tk.StringVar | None = None


def _safe_set(var: tk.StringVar | None, text: str):
    if root is None or var is None:
        return
    try:
        root.after(0, lambda: var.set(text))
    except Exception:
        pass


def _on_history(data):
    if isinstance(data, list):
        message_log.clear()
        message_log.extend(data)
        while True:
            try:
                message_queue.get_nowait()
            except queue.Empty:
                break
        for m in data:
            message_queue.put(m)


def _on_new_comment(entry):
    if isinstance(entry, dict):
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
        root.geometry(f"{w}x{h}+{scr.x + scr.width - w}+{scr.y}")
        root.resizable(False, True)

    update_monitor_position()
    root.configure(bg="#fefefe")
    root.attributes("-topmost", True)
    root.update()
    set_always_on_top(root.winfo_id())

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
html, body { overflow-y: auto; overflow-x: hidden; -ms-overflow-style: none; scrollbar-width: none; }
body::-webkit-scrollbar { width: 0; height: 0; }
*::-webkit-scrollbar { width: 0; height: 0; }
</style>
""".strip()

    if "</head>" in bubble_html:
        base_html = bubble_html.replace("</head>", f"{style_block}</head>")
    elif "<body" in bubble_html:
        base_html = bubble_html.replace("<body>", f"<body>{style_block}")
    else:
        base_html = style_block + bubble_html

    def update_comments():
        try:
            while True:
                messages.append(message_queue.get_nowait())
        except queue.Empty:
            pass
        body = "\n".join(
            f"""
            <div class="comment-wrapper">
              <div class="shadow-box"></div>
              <div class="comment-box">
                <div class="name-label">{html.escape(m.get('name',''))}</div>
                <div class="comment-name-time">
                  <span>　</span>
                  <span style='font-weight:normal;color:#666;'>{html.escape(m.get('time','')[11:16] if isinstance(m.get('time',''), str) else '')}</span>
                </div>
                <div class="comment-text">{html.escape(m.get('text',''))}</div>
                <div class="like"></div>
              </div>
            </div>
            """
            for m in reversed(messages)
        )
        full_html = base_html.replace("</body>", f"{body}</body>")
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
        try:
            if sio.connected:
                sio.disconnect()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
