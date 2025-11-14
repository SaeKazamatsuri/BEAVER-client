from __future__ import annotations

import io

import openpyxl  # noqa: F401
import pandas as pd
import tkinter as tk
import tkinter.ttk as ttk
import win32con
import win32gui
from tkinter import filedialog, messagebox

import app_state as state
from events import connect_session


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
    tree.heading("time", text="時間")
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
        current_len = len(state.message_log)
        if current_len != last_count[0]:
            tree.delete(*tree.get_children())
            snapshot = list(state.message_log)
            for e in snapshot:
                tree.insert("", "end", values=make_row(e))
            last_count[0] = current_len
        win.after(500, refresh)

    refresh()


def create_menu_window(switch_display_callback, root_ref: tk.Tk):
    menu = tk.Toplevel(root_ref)
    menu.title("コントローラーメニュー")
    menu.geometry("350x420")
    menu.attributes("-topmost", True)

    state.menu_status_var = tk.StringVar(value="未接続")
    state.menu_current_session_var = tk.StringVar(value="現在のセッション: なし")
    state.menu_session_var = tk.StringVar(value="default")

    tk.Label(menu, textvariable=state.menu_status_var).pack(pady=(10, 5))
    tk.Label(menu, textvariable=state.menu_current_session_var).pack(pady=(0, 10))

    frame = tk.Frame(menu)
    frame.pack(pady=5, fill="x", padx=10)
    tk.Label(frame, text="セッションID").grid(row=0, column=0, sticky="w")
    entry = tk.Entry(frame, textvariable=state.menu_session_var, width=28)
    entry.grid(row=1, column=0, padx=(0, 8), pady=(2, 0), sticky="w")
    tk.Button(
        frame,
        text="接続",
        command=lambda: connect_session(state.menu_session_var.get().strip()),
    ).grid(row=1, column=1, sticky="e")

    def export_dialog(fmt: str):
        if not state.message_log:
            messagebox.showinfo("保存", "データがありません")
            return
        df = pd.DataFrame(state.message_log).rename(
            columns={
                "real_name": "本名",
                "name": "名前",
                "text": "コメント",
                "time": "時間",
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
        if messagebox.askokcancel("終了", "アプリを終了しますか？"):
            try:
                if state.sio.connected:
                    state.sio.disconnect()
            except Exception:
                pass
            root_ref.destroy()

    tk.Button(menu, text="ディスプレイ切替", command=switch_display_callback).pack(
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
