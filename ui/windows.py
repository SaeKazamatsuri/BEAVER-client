from __future__ import annotations

import io
from collections.abc import Callable
from datetime import datetime

import openpyxl  # noqa: F401
import pandas as pd
import tkinter as tk
import tkinter.ttk as ttk
import win32con
import win32gui
from tkinter import filedialog, messagebox

from services.events import connect_session, disconnect_session
from services.transcription_service import stop_transcription_service
from state import app_state as state


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


def _string_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def _format_timestamp(value: object) -> str:
    raw_value = _string_value(value)
    if not raw_value:
        return "-"
    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw_value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _transcription_badge_colors(badge: str) -> tuple[str, str]:
    palette = {
        "未接続": ("#475569", "#e2e8f0"),
        "起動中": ("#9a3412", "#ffedd5"),
        "待機中": ("#1d4ed8", "#dbeafe"),
        "稼働中": ("#047857", "#d1fae5"),
        "異常": ("#b91c1c", "#fee2e2"),
        "停止": ("#374151", "#e5e7eb"),
    }
    return palette.get(badge, ("#0f172a", "#e2e8f0"))


def _build_transcription_timeline(
    items: list[dict[str, object]],
    events: list[dict[str, object]],
) -> list[dict[str, object]]:
    timeline: list[dict[str, object]] = []

    for item in items:
        item_id = item.get("id")
        sort_order = item_id if isinstance(item_id, int) else 0
        timeline.append(
            {
                "kind": "transcription",
                "created_at": _string_value(item.get("created_at")),
                "title": "文字起こし",
                "body": _string_value(item.get("text")),
                "sort_order": sort_order,
            }
        )

    event_count = len(events)
    for index, event in enumerate(events):
        timeline.append(
            {
                "kind": "status",
                "created_at": _string_value(event.get("created_at")),
                "title": _string_value(event.get("event")) or "状態更新",
                "body": _string_value(event.get("detail")),
                "sort_order": event_count - index,
            }
        )

    timeline.sort(
        key=lambda entry: (
            _string_value(entry.get("created_at")),
            1 if entry.get("kind") == "transcription" else 0,
            int(entry.get("sort_order", 0)),
        ),
        reverse=True,
    )
    return timeline


def _render_transcription_timeline(
    parent: tk.Frame,
    timeline: list[dict[str, object]],
    session_connected: bool,
) -> None:
    for child in parent.winfo_children():
        child.destroy()

    if not timeline:
        placeholder = (
            "現在セッション未接続のため、状態イベントのみ表示します。"
            if not session_connected
            else "まだ文字起こし履歴はありません。"
        )
        tk.Label(
            parent,
            text=placeholder,
            bg="#eef3f7",
            fg="#475569",
            justify="left",
            wraplength=640,
            anchor="w",
            padx=12,
            pady=20,
        ).pack(fill="x")
        return

    for entry in timeline:
        kind = _string_value(entry.get("kind"))
        if kind == "transcription":
            accent = "#0f766e"
            tag_bg = "#ccfbf1"
            card_bg = "#ffffff"
            tag_text = "TEXT"
        else:
            accent = "#1d4ed8"
            tag_bg = "#dbeafe"
            card_bg = "#f8fbff"
            tag_text = "STATUS"

        card = tk.Frame(
            parent,
            bg=card_bg,
            highlightbackground="#d7e2ec",
            highlightthickness=1,
            bd=0,
            padx=16,
            pady=14,
        )
        card.pack(fill="x", padx=8, pady=6)

        header = tk.Frame(card, bg=card_bg)
        header.pack(fill="x")

        tk.Label(
            header,
            text=tag_text,
            bg=tag_bg,
            fg=accent,
            padx=10,
            pady=2,
            font=("Yu Gothic UI", 9, "bold"),
        ).pack(side="left")

        tk.Label(
            header,
            text=_string_value(entry.get("title")),
            bg=card_bg,
            fg="#0f172a",
            font=("Yu Gothic UI", 11, "bold"),
        ).pack(side="left", padx=(10, 0))

        tk.Label(
            header,
            text=_format_timestamp(entry.get("created_at")),
            bg=card_bg,
            fg="#64748b",
            font=("Yu Gothic UI", 9),
        ).pack(side="right")

        tk.Label(
            card,
            text=_string_value(entry.get("body")) or "-",
            bg=card_bg,
            fg="#1e293b",
            justify="left",
            anchor="w",
            wraplength=620,
            padx=2,
            pady=10,
            font=("Yu Gothic UI", 11),
        ).pack(fill="x")


def _open_transcription_history_window(root_ref: tk.Tk):
    existing = state.transcription_history_window
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

    win = tk.Toplevel(root_ref)
    state.transcription_history_window = win
    win.title("文字起こし履歴")
    win.geometry("760x720")
    win.configure(bg="#eef3f7")

    def on_close() -> None:
        try:
            win.destroy()
        finally:
            state.transcription_history_window = None

    win.protocol("WM_DELETE_WINDOW", on_close)

    wrapper = tk.Frame(win, bg="#eef3f7", padx=16, pady=16)
    wrapper.pack(expand=True, fill="both")

    tk.Label(
        wrapper,
        text="文字起こし状態",
        bg="#eef3f7",
        fg="#0f172a",
        font=("Yu Gothic UI", 16, "bold"),
        anchor="w",
    ).pack(fill="x")

    summary = tk.Frame(
        wrapper,
        bg="#ffffff",
        highlightbackground="#d7e2ec",
        highlightthickness=1,
        padx=18,
        pady=16,
    )
    summary.pack(fill="x", pady=(12, 14))

    session_var = tk.StringVar(value="現在のセッション: なし")
    badge_var = tk.StringVar(value="未接続")
    success_var = tk.StringVar(value="最終成功: -")
    error_var = tk.StringVar(value="最終エラー: -")

    header = tk.Frame(summary, bg="#ffffff")
    header.pack(fill="x")

    tk.Label(
        header,
        textvariable=session_var,
        bg="#ffffff",
        fg="#0f172a",
        font=("Yu Gothic UI", 11, "bold"),
    ).pack(side="left")

    badge_label = tk.Label(
        header,
        textvariable=badge_var,
        bg="#e2e8f0",
        fg="#475569",
        padx=12,
        pady=4,
        font=("Yu Gothic UI", 10, "bold"),
    )
    badge_label.pack(side="right")

    tk.Label(
        summary,
        textvariable=success_var,
        bg="#ffffff",
        fg="#334155",
        anchor="w",
        justify="left",
        font=("Yu Gothic UI", 10),
        pady=8,
    ).pack(fill="x")

    tk.Label(
        summary,
        textvariable=error_var,
        bg="#ffffff",
        fg="#334155",
        anchor="w",
        justify="left",
        wraplength=660,
        font=("Yu Gothic UI", 10),
    ).pack(fill="x")

    tk.Label(
        wrapper,
        text="タイムライン",
        bg="#eef3f7",
        fg="#0f172a",
        font=("Yu Gothic UI", 13, "bold"),
        anchor="w",
    ).pack(fill="x")

    timeline_frame = tk.Frame(wrapper, bg="#eef3f7")
    timeline_frame.pack(expand=True, fill="both", pady=(10, 0))

    canvas = tk.Canvas(
        timeline_frame,
        bg="#eef3f7",
        highlightthickness=0,
        bd=0,
    )
    scrollbar = ttk.Scrollbar(
        timeline_frame,
        orient="vertical",
        command=canvas.yview,
    )
    content = tk.Frame(canvas, bg="#eef3f7")
    content_window = canvas.create_window((0, 0), window=content, anchor="nw")

    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", expand=True, fill="both")
    scrollbar.pack(side="right", fill="y")

    content.bind(
        "<Configure>",
        lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
    )
    canvas.bind(
        "<Configure>",
        lambda event: canvas.itemconfigure(content_window, width=event.width),
    )

    last_signature = [None]

    def refresh() -> None:
        if not win.winfo_exists():
            return

        status, items, events = state.snapshot_transcription_history()
        timeline = _build_transcription_timeline(items, events)
        signature = (
            _string_value(status.get("badge")),
            _string_value(status.get("session")),
            _string_value(status.get("last_success_at")),
            _string_value(status.get("last_error_at")),
            _string_value(status.get("last_error_message")),
            len(items),
            len(events),
            tuple(
                (
                    item.get("id"),
                    _string_value(item.get("created_at")),
                    _string_value(item.get("text")),
                )
                for item in items[-5:]
            ),
            tuple(
                (
                    _string_value(event.get("event")),
                    _string_value(event.get("created_at")),
                )
                for event in events[-5:]
            ),
        )

        if signature != last_signature[0]:
            session_name = _string_value(status.get("session")) or "なし"
            session_var.set(f"現在のセッション: {session_name}")

            badge = _string_value(status.get("badge")) or "未接続"
            badge_var.set(badge)
            badge_fg, badge_bg = _transcription_badge_colors(badge)
            badge_label.configure(bg=badge_bg, fg=badge_fg)

            success_var.set(
                f"最終成功: {_format_timestamp(status.get('last_success_at'))}"
            )

            last_error_at = _format_timestamp(status.get("last_error_at"))
            last_error_message = _string_value(status.get("last_error_message"))
            if last_error_at == "-" and not last_error_message:
                error_text = "最終エラー: -"
            elif last_error_message:
                error_text = f"最終エラー: {last_error_at} / {last_error_message}"
            else:
                error_text = f"最終エラー: {last_error_at}"
            error_var.set(error_text)

            _render_transcription_timeline(
                content,
                timeline,
                bool(_string_value(status.get("session"))),
            )
            last_signature[0] = signature

        win.after(500, refresh)

    refresh()


def _open_experiment_window(
    root_ref: tk.Tk,
    refresh_layout_callback: Callable[[], None],
) -> None:
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

    def set_area_mode() -> None:
        state.stamp_area_mode = area_var.get()
        refresh_corner_controls()
        try:
            refresh_layout_callback()
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
    corner_frame = ttk.LabelFrame(container, text="出現位置（左75%のとき有効）")
    corner_frame.pack(fill="x", pady=(0, 10))
    initial_corner = getattr(state, "stamp_origin_corner", "bottom_right")
    if initial_corner not in ("bottom_left", "bottom_right"):
        initial_corner = "bottom_right" if "right" in str(initial_corner) else "bottom_left"
    state.stamp_origin_corner = initial_corner
    corner_var = tk.StringVar(value=initial_corner)

    def set_corner() -> None:
        state.stamp_origin_corner = corner_var.get()

    corner_grid = ttk.Frame(corner_frame)
    corner_grid.pack(anchor="w", padx=8, pady=6)
    rb_corner_left = ttk.Radiobutton(
        corner_grid,
        text="左下",
        value="bottom_left",
        variable=corner_var,
        command=set_corner,
    )
    rb_corner_left.grid(row=0, column=0, sticky="w", padx=(0, 16), pady=2)
    rb_corner_right = ttk.Radiobutton(
        corner_grid,
        text="右下",
        value="bottom_right",
        variable=corner_var,
        command=set_corner,
    )
    rb_corner_right.grid(row=0, column=1, sticky="w", pady=2)

    def refresh_corner_controls() -> None:
        enabled = area_var.get() == "left75"
        state_str = "normal" if enabled else "disabled"
        rb_corner_left.configure(state=state_str)
        rb_corner_right.configure(state=state_str)

    refresh_corner_controls()

    # --- Speed range ---
    speed_frame = ttk.LabelFrame(container, text="移動速度（px/秒）")
    speed_frame.pack(fill="x", pady=(0, 10))
    speed_min_var = tk.DoubleVar(value=getattr(state, "stamp_speed_min_px_s", 90.0))
    speed_max_var = tk.DoubleVar(value=getattr(state, "stamp_speed_max_px_s", 200.0))

    def set_speed_min(value: str) -> None:
        try:
            v = float(value)
        except Exception:
            return
        state.stamp_speed_min_px_s = v
        if v > float(speed_max_var.get()):
            speed_max_var.set(v)
            state.stamp_speed_max_px_s = v

    def set_speed_max(value: str) -> None:
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
    distance_frame = ttk.LabelFrame(container, text="移動距離の上限（%）")
    distance_frame.pack(fill="x", pady=(0, 10))
    distance_var = tk.DoubleVar(
        value=getattr(state, "stamp_distance_limit_percent", 0.0)
    )

    def set_distance(value: str) -> None:
        try:
            v = float(value)
        except Exception:
            return
        state.stamp_distance_limit_percent = max(0.0, min(100.0, v))

    ttk.Label(distance_frame, text="0 = 無制限 / 100 = 画面の高さ分").pack(
        anchor="w", padx=8
    )
    tk.Scale(
        distance_frame,
        from_=0,
        to=100,
        orient="horizontal",
        resolution=1,
        showvalue=True,
        variable=distance_var,
        command=set_distance,
    ).pack(fill="x", padx=8, pady=(0, 6))

    # --- Lifetime ---
    lifetime_frame = ttk.LabelFrame(container, text="強制非表示（秒）")
    lifetime_frame.pack(fill="x", pady=(0, 10))
    lifetime_var = tk.DoubleVar(value=getattr(state, "stamp_lifetime_sec", 8.0))

    def set_lifetime(value: str) -> None:
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

    def reset_defaults() -> None:
        state.reset_stamp_experiment_settings()
        area_var.set(state.stamp_area_mode)
        corner_var.set(state.stamp_origin_corner)
        speed_min_var.set(state.stamp_speed_min_px_s)
        speed_max_var.set(state.stamp_speed_max_px_s)
        distance_var.set(state.stamp_distance_limit_percent)
        lifetime_var.set(state.stamp_lifetime_sec)
        set_area_mode()

    ttk.Button(actions, text="デフォルトに戻す", command=reset_defaults).pack(
        side="left"
    )
    ttk.Button(actions, text="閉じる", command=on_close).pack(side="right")


def create_menu_window(
    switch_display_callback: Callable[[], None],
    refresh_layout_callback: Callable[[], None],
    root_ref: tk.Tk,
) -> None:
    menu = tk.Toplevel(root_ref)
    menu.title("コントローラーメニュー")
    menu.geometry("350x470")
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
            disconnect_session(show_status=False)
            stop_transcription_service()
            root_ref.destroy()

    tk.Button(menu, text="ディスプレイ切替", command=switch_display_callback).pack(
        pady=8
    )
    tk.Button(
        menu,
        text="実験",
        command=lambda: _open_experiment_window(root_ref, refresh_layout_callback),
    ).pack(pady=5)
    tk.Button(
        menu, text="コメント履歴", command=lambda: _open_history_window(root_ref)
    ).pack(pady=5)
    tk.Button(
        menu,
        text="文字起こし履歴",
        command=lambda: _open_transcription_history_window(root_ref),
    ).pack(pady=5)
    tk.Button(menu, text="CSV で保存", command=lambda: export_dialog("csv")).pack(
        pady=5
    )
    tk.Button(menu, text="Excel で保存", command=lambda: export_dialog("xlsx")).pack(
        pady=5
    )
    tk.Button(menu, text="アプリ終了", command=confirm_exit).pack(pady=12)
