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


def _open_experiment_window(root_ref: tk.Tk):
    existing = state.experiment_window
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

    win = tk.Toplevel(root_ref)
    state.experiment_window = win
    win.title("実験")
    win.geometry("460x520")
    win.attributes("-topmost", True)

    def on_close():
        try:
            win.destroy()
        finally:
            state.experiment_window = None

    win.protocol("WM_DELETE_WINDOW", on_close)

    container = ttk.Frame(win, padding=12)
    container.pack(expand=True, fill="both")

    ttk.Label(
        container,
        text="スタンプ表示の実験用パラメータを変更できます（次のスタンプから反映）",
        wraplength=420,
        justify="left",
    ).pack(anchor="w", pady=(0, 12))

    # --- Area mode ---
    area_frame = ttk.LabelFrame(container, text="表示領域")
    area_frame.pack(fill="x", pady=(0, 10))
    area_var = tk.StringVar(value=getattr(state, "stamp_area_mode", "comment"))

    def set_area_mode():
        state.stamp_area_mode = area_var.get()
        cb = getattr(state, "request_layout_refresh", None)
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    ttk.Radiobutton(
        area_frame,
        text="コメント欄（右25%）",
        value="comment",
        variable=area_var,
        command=set_area_mode,
    ).pack(anchor="w", padx=8, pady=2)
    ttk.Radiobutton(
        area_frame,
        text="左75%",
        value="left75",
        variable=area_var,
        command=set_area_mode,
    ).pack(anchor="w", padx=8, pady=2)

    # --- Origin corner ---
    corner_frame = ttk.LabelFrame(container, text="出現位置")
    corner_frame.pack(fill="x", pady=(0, 10))
    corner_var = tk.StringVar(
        value=getattr(state, "stamp_origin_corner", "bottom_right")
    )

    def set_corner():
        state.stamp_origin_corner = corner_var.get()

    corner_grid = ttk.Frame(corner_frame)
    corner_grid.pack(anchor="w", padx=8, pady=6)
    ttk.Radiobutton(
        corner_grid,
        text="左上",
        value="top_left",
        variable=corner_var,
        command=set_corner,
    ).grid(row=0, column=0, sticky="w", padx=(0, 16), pady=2)
    ttk.Radiobutton(
        corner_grid,
        text="右上",
        value="top_right",
        variable=corner_var,
        command=set_corner,
    ).grid(row=0, column=1, sticky="w", pady=2)
    ttk.Radiobutton(
        corner_grid,
        text="左下",
        value="bottom_left",
        variable=corner_var,
        command=set_corner,
    ).grid(row=1, column=0, sticky="w", padx=(0, 16), pady=2)
    ttk.Radiobutton(
        corner_grid,
        text="右下",
        value="bottom_right",
        variable=corner_var,
        command=set_corner,
    ).grid(row=1, column=1, sticky="w", pady=2)

    # --- Speed range ---
    speed_frame = ttk.LabelFrame(container, text="移動速度（px/秒）")
    speed_frame.pack(fill="x", pady=(0, 10))
    speed_min_var = tk.DoubleVar(value=getattr(state, "stamp_speed_min_px_s", 90.0))
    speed_max_var = tk.DoubleVar(value=getattr(state, "stamp_speed_max_px_s", 200.0))

    def set_speed_min(value: str):
        try:
            v = float(value)
        except Exception:
            return
        state.stamp_speed_min_px_s = v
        if v > float(speed_max_var.get()):
            speed_max_var.set(v)
            state.stamp_speed_max_px_s = v

    def set_speed_max(value: str):
        try:
            v = float(value)
        except Exception:
            return
        state.stamp_speed_max_px_s = v
        if v < float(speed_min_var.get()):
            speed_min_var.set(v)
            state.stamp_speed_min_px_s = v

    tk.Label(speed_frame, text="最小").pack(anchor="w", padx=8)
    tk.Scale(
        speed_frame,
        from_=10,
        to=600,
        orient="horizontal",
        resolution=1,
        showvalue=True,
        variable=speed_min_var,
        command=set_speed_min,
    ).pack(fill="x", padx=8, pady=(0, 6))
    tk.Label(speed_frame, text="最大").pack(anchor="w", padx=8)
    tk.Scale(
        speed_frame,
        from_=10,
        to=600,
        orient="horizontal",
        resolution=1,
        showvalue=True,
        variable=speed_max_var,
        command=set_speed_max,
    ).pack(fill="x", padx=8, pady=(0, 6))

    # --- Distance limit ---
    distance_frame = ttk.LabelFrame(container, text="移動距離の上限（px）")
    distance_frame.pack(fill="x", pady=(0, 10))
    distance_var = tk.DoubleVar(value=getattr(state, "stamp_distance_limit_px", 0.0))

    def set_distance(value: str):
        try:
            v = float(value)
        except Exception:
            return
        state.stamp_distance_limit_px = max(0.0, v)

    ttk.Label(distance_frame, text="0 = 無制限").pack(anchor="w", padx=8)
    tk.Scale(
        distance_frame,
        from_=0,
        to=6000,
        orient="horizontal",
        resolution=10,
        showvalue=True,
        variable=distance_var,
        command=set_distance,
    ).pack(fill="x", padx=8, pady=(0, 6))

    # --- Lifetime ---
    lifetime_frame = ttk.LabelFrame(container, text="表示時間（秒）")
    lifetime_frame.pack(fill="x", pady=(0, 10))
    lifetime_var = tk.DoubleVar(value=getattr(state, "stamp_lifetime_sec", 8.0))

    def set_lifetime(value: str):
        try:
            v = float(value)
        except Exception:
            return
        state.stamp_lifetime_sec = max(0.1, v)

    tk.Scale(
        lifetime_frame,
        from_=0.5,
        to=60.0,
        orient="horizontal",
        resolution=0.5,
        showvalue=True,
        variable=lifetime_var,
        command=set_lifetime,
    ).pack(fill="x", padx=8, pady=(6, 6))

    # --- Actions ---
    actions = ttk.Frame(container)
    actions.pack(fill="x", pady=(8, 0))

    def reset_defaults():
        state.reset_stamp_experiment_settings()
        area_var.set(state.stamp_area_mode)
        corner_var.set(state.stamp_origin_corner)
        speed_min_var.set(state.stamp_speed_min_px_s)
        speed_max_var.set(state.stamp_speed_max_px_s)
        distance_var.set(state.stamp_distance_limit_px)
        lifetime_var.set(state.stamp_lifetime_sec)
        set_area_mode()

    ttk.Button(actions, text="デフォルトに戻す", command=reset_defaults).pack(
        side="left"
    )
    ttk.Button(actions, text="閉じる", command=on_close).pack(side="right")


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
    tk.Button(menu, text="実験", command=lambda: _open_experiment_window(root_ref)).pack(
        pady=5
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
