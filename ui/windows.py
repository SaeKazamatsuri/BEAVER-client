from __future__ import annotations

import io
from collections.abc import Callable, Sequence

import tkinter as tk
from tkinter import filedialog, messagebox

from services.events import connect_session, disconnect_session
from services.transcription_service import stop_transcription_service
from state import app_state as state
from ui.admin_cards import (
    AdminListCard,
    CommentHistoryRow,
    build_comment_history_rows,
    build_comment_history_signature,
    build_transcription_timeline,
    format_timestamp as _format_timestamp,
    string_value as _string_value,
)
from ui.file_utils import build_export_filename
from ui import admin_theme

try:
    import win32con
    import win32gui
except ModuleNotFoundError:
    win32con = None
    win32gui = None


def set_always_on_top(hwnd: int) -> None:
    if win32con is None or win32gui is None:
        return
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
    )


def _default_export_filename(extension: str) -> str:
    session_name = _string_value(getattr(state, "CURRENT_SESSION", "")).strip()
    if not session_name:
        menu_session_var = state.menu_session_var
        if menu_session_var is not None:
            session_name = menu_session_var.get().strip()
    return build_export_filename(session_name, extension)


def _focus_existing_window(window: tk.Toplevel | None) -> bool:
    if window is None:
        return False
    try:
        if window.winfo_exists():
            window.lift()
            window.focus_force()
            return True
    except Exception:
        return False
    return False


def _create_window_header(
    parent: tk.Misc,
    *,
    title: str,
    description: str,
    wraplength: int = 680,
) -> None:
    tk.Label(
        parent,
        text=title,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.WINDOW_TITLE_FONT,
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        parent,
        text=description,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.SUBTLE_TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        justify="left",
        anchor="w",
        wraplength=wraplength,
        pady=6,
    ).pack(fill="x")


def _create_section_label(parent: tk.Misc, text: str) -> None:
    tk.Label(
        parent,
        text=text,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.SECTION_TITLE_FONT,
        anchor="w",
        pady=2,
    ).pack(fill="x")


def _create_titled_card(
    parent: tk.Misc,
    *,
    title: str,
    description: str | None = None,
    background: str = admin_theme.SURFACE_BG,
    wraplength: int = 680,
) -> tk.Frame:
    card = admin_theme.create_card(parent, background=background)
    card.pack(fill="x", pady=(10, 0))
    tk.Label(
        card,
        text=title,
        bg=background,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.CARD_TITLE_FONT,
        anchor="w",
    ).pack(fill="x")
    if description:
        tk.Label(
            card,
            text=description,
            bg=background,
            fg=admin_theme.SUBTLE_TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            justify="left",
            anchor="w",
            wraplength=wraplength,
            pady=6,
        ).pack(fill="x")
    return card


def _render_card_list(
    parent: tk.Frame,
    cards: Sequence[AdminListCard],
    *,
    empty_message: str,
) -> None:
    for child in parent.winfo_children():
        child.destroy()

    if not cards:
        tk.Label(
            parent,
            text=empty_message,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.SUBTLE_TEXT_COLOR,
            justify="left",
            wraplength=640,
            anchor="w",
            padx=12,
            pady=20,
            font=admin_theme.BODY_FONT,
        ).pack(fill="x")
        return

    for entry in cards:
        palette = admin_theme.get_list_card_palette(entry.kind)
        card = admin_theme.create_card(
            parent,
            background=palette.card_background,
            padx=16,
            pady=14,
        )
        card.pack(fill="x", padx=8, pady=6)

        header = tk.Frame(card, bg=palette.card_background)
        header.pack(fill="x")

        tk.Label(
            header,
            text=entry.tag_text,
            bg=palette.tag_background,
            fg=palette.accent,
            padx=10,
            pady=2,
            font=admin_theme.SMALL_BOLD_FONT,
        ).pack(side="left")

        tk.Label(
            header,
            text=entry.title or "-",
            bg=palette.card_background,
            fg=admin_theme.TITLE_COLOR,
            font=admin_theme.CARD_TITLE_FONT,
        ).pack(side="left", padx=(10, 0))

        tk.Label(
            header,
            text=entry.timestamp,
            bg=palette.card_background,
            fg=admin_theme.MUTED_TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
        ).pack(side="right")

        tk.Label(
            card,
            text=entry.body or "-",
            bg=palette.card_background,
            fg=admin_theme.TEXT_COLOR,
            justify="left",
            anchor="w",
            wraplength=620,
            padx=2,
            pady=10,
            font=admin_theme.BODY_FONT,
        ).pack(fill="x")


def _render_comment_history_rows(
    parent: tk.Frame,
    rows: Sequence[CommentHistoryRow],
    *,
    empty_message: str,
) -> None:
    for child in parent.winfo_children():
        child.destroy()

    if not rows:
        tk.Label(
            parent,
            text=empty_message,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.SUBTLE_TEXT_COLOR,
            justify="left",
            wraplength=640,
            anchor="w",
            padx=6,
            pady=12,
            font=admin_theme.BODY_FONT,
        ).pack(fill="x")
        return

    last_index = len(rows) - 1
    for index, entry in enumerate(rows):
        row = tk.Frame(parent, bg=admin_theme.WINDOW_BG, padx=6, pady=4)
        row.pack(fill="x")
        row.grid_columnconfigure(2, weight=1)

        tk.Label(
            row,
            text=entry.timestamp,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.MUTED_TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            anchor="w",
            width=10,
        ).grid(row=0, column=0, sticky="nw", padx=(0, 10))

        tk.Label(
            row,
            text=entry.name,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.TITLE_COLOR,
            font=admin_theme.SMALL_BOLD_FONT,
            anchor="w",
            width=12,
        ).grid(row=0, column=1, sticky="nw", padx=(0, 10))

        tk.Label(
            row,
            text=entry.text,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.TEXT_COLOR,
            font=admin_theme.BODY_FONT,
            justify="left",
            anchor="w",
            wraplength=520,
        ).grid(row=0, column=2, sticky="nsew")

        if index < last_index:
            tk.Frame(parent, bg=admin_theme.BORDER_COLOR, height=1).pack(
                fill="x",
                padx=6,
                pady=(0, 4),
            )


def _create_dashboard_button_row(
    parent: tk.Misc,
    *,
    left_text: str,
    left_command: Callable[[], None],
    right_text: str,
    right_command: Callable[[], None],
) -> None:
    row = tk.Frame(parent, bg=admin_theme.WINDOW_BG)
    row.pack(fill="x", pady=(0, 10))

    admin_theme.create_button(
        row,
        text=left_text,
        command=left_command,
        variant="secondary",
    ).pack(side="left", expand=True, fill="x")

    admin_theme.create_button(
        row,
        text=right_text,
        command=right_command,
        variant="secondary",
    ).pack(side="left", expand=True, fill="x", padx=(10, 0))


def _open_history_window(root_ref: tk.Tk) -> None:
    win = tk.Toplevel(root_ref)
    win.title("コメント履歴")

    wrapper = admin_theme.create_window_shell(win, geometry="760x720")
    count_var = tk.StringVar(value="表示件数: 0 件")
    tk.Label(
        wrapper,
        textvariable=count_var,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.SECTION_TITLE_FONT,
        anchor="w",
        pady=2,
    ).pack(fill="x")

    timeline_frame, content = admin_theme.create_scrollable_panel(
        wrapper,
        background=admin_theme.WINDOW_BG,
    )
    timeline_frame.pack(expand=True, fill="both", pady=(8, 0))

    last_signature: list[tuple[tuple[str, str, str, str], ...] | None] = [None]

    def refresh() -> None:
        if not win.winfo_exists():
            return

        snapshot = list(state.message_log)
        signature = build_comment_history_signature(snapshot)
        if signature != last_signature[0]:
            rows = build_comment_history_rows(snapshot)
            count_var.set(f"表示件数: {len(rows)} 件")
            _render_comment_history_rows(
                content,
                rows,
                empty_message="まだテキストコメント履歴はありません。",
            )
            last_signature[0] = signature

        win.after(500, refresh)

    refresh()


def _open_transcription_history_window(root_ref: tk.Tk) -> None:
    if _focus_existing_window(state.transcription_history_window):
        return

    win = tk.Toplevel(root_ref)
    state.transcription_history_window = win
    win.title("文字起こし履歴")

    def on_close() -> None:
        try:
            win.destroy()
        finally:
            state.transcription_history_window = None

    win.protocol("WM_DELETE_WINDOW", on_close)

    wrapper = admin_theme.create_window_shell(win, geometry="760x720")
    _create_window_header(
        wrapper,
        title="文字起こし履歴",
        description="文字起こし状態とイベントを、管理UI共通のカードレイアウトで確認できます。",
        wraplength=680,
    )

    _create_section_label(wrapper, "文字起こし状態")
    summary = admin_theme.create_card(wrapper)
    summary.pack(fill="x", pady=(10, 14))

    session_var = tk.StringVar(value="現在のセッション: なし")
    badge_var = tk.StringVar(value="未接続")
    success_var = tk.StringVar(value="最終成功: -")
    error_var = tk.StringVar(value="最終エラー: -")

    header = tk.Frame(summary, bg=admin_theme.SURFACE_BG)
    header.pack(fill="x")

    tk.Label(
        header,
        textvariable=session_var,
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.CARD_TITLE_FONT,
        anchor="w",
    ).pack(side="left")

    badge_label = admin_theme.create_badge(header, textvariable=badge_var)
    badge_label.pack(side="right")

    tk.Label(
        summary,
        textvariable=success_var,
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        anchor="w",
        justify="left",
        font=admin_theme.SMALL_FONT,
        pady=8,
    ).pack(fill="x")

    tk.Label(
        summary,
        textvariable=error_var,
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        anchor="w",
        justify="left",
        wraplength=660,
        font=admin_theme.SMALL_FONT,
    ).pack(fill="x")

    _create_section_label(wrapper, "タイムライン")
    timeline_frame, content = admin_theme.create_scrollable_panel(
        wrapper,
        background=admin_theme.WINDOW_BG,
    )
    timeline_frame.pack(expand=True, fill="both", pady=(10, 0))

    last_signature: list[object | None] = [None]

    def refresh() -> None:
        if not win.winfo_exists():
            return

        status, items, events = state.snapshot_transcription_history()
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
            admin_theme.update_badge(badge_label, badge)

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

            empty_message = (
                "現在セッション未接続のため、状態イベントのみ表示します。"
                if not _string_value(status.get("session"))
                else "まだ文字起こし履歴はありません。"
            )
            _render_card_list(
                content,
                build_transcription_timeline(items, events),
                empty_message=empty_message,
            )
            last_signature[0] = signature

        win.after(500, refresh)

    refresh()


def _open_experiment_window(
    root_ref: tk.Tk,
    _refresh_layout_callback: Callable[[], None],
) -> None:
    if _focus_existing_window(state.experiment_window):
        return

    win = tk.Toplevel(root_ref)
    state.experiment_window = win
    win.title("実験")

    def on_close() -> None:
        try:
            win.destroy()
        finally:
            state.experiment_window = None

    win.protocol("WM_DELETE_WINDOW", on_close)

    wrapper = admin_theme.create_window_shell(
        win,
        geometry="560x760",
        topmost=True,
    )
    _create_window_header(
        wrapper,
        title="実験パラメータ",
        description="右25%のコメント欄に重ねて表示するスタンプの実験用パラメータを変更できます。変更は次のスタンプから反映されます。",
        wraplength=500,
    )

    scroll_frame, content = admin_theme.create_scrollable_panel(
        wrapper,
        background=admin_theme.WINDOW_BG,
    )
    scroll_frame.pack(expand=True, fill="both", pady=(10, 0))

    speed_min_var = tk.DoubleVar(value=getattr(state, "stamp_speed_min_px_s", 90.0))
    speed_max_var = tk.DoubleVar(value=getattr(state, "stamp_speed_max_px_s", 200.0))
    distance_var = tk.DoubleVar(
        value=getattr(state, "stamp_distance_limit_percent", 0.0)
    )
    lifetime_var = tk.DoubleVar(value=getattr(state, "stamp_lifetime_sec", 8.0))

    speed_card = _create_titled_card(
        content,
        title="移動速度（px/秒）",
        description="スタンプの移動速度の下限と上限を調整します。",
        wraplength=460,
    )

    distance_card = _create_titled_card(
        content,
        title="移動距離の上限（%）",
        description="0 は無制限、100 は画面の高さ分です。",
        wraplength=460,
    )

    lifetime_card = _create_titled_card(
        content,
        title="強制非表示（秒）",
        description="スタンプを強制的に非表示にするまでの秒数です。",
        wraplength=460,
    )

    actions_card = _create_titled_card(
        content,
        title="操作",
        description="実験値を初期値に戻すか、このウィンドウを閉じます。",
        wraplength=460,
    )

    tk.Label(
        speed_card,
        text="最小",
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    def set_speed_min(value: str) -> None:
        try:
            speed_value = float(value)
        except ValueError:
            return
        state.stamp_speed_min_px_s = speed_value
        if speed_value > float(speed_max_var.get()):
            speed_max_var.set(speed_value)
            state.stamp_speed_max_px_s = speed_value

    admin_theme.create_scale(
        speed_card,
        variable=speed_min_var,
        from_=10,
        to=600,
        resolution=1,
        command=set_speed_min,
        background=admin_theme.SURFACE_BG,
    ).pack(fill="x", pady=(2, 8))

    tk.Label(
        speed_card,
        text="最大",
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x")

    def set_speed_max(value: str) -> None:
        try:
            speed_value = float(value)
        except ValueError:
            return
        state.stamp_speed_max_px_s = speed_value
        if speed_value < float(speed_min_var.get()):
            speed_min_var.set(speed_value)
            state.stamp_speed_min_px_s = speed_value

    admin_theme.create_scale(
        speed_card,
        variable=speed_max_var,
        from_=10,
        to=600,
        resolution=1,
        command=set_speed_max,
        background=admin_theme.SURFACE_BG,
    ).pack(fill="x", pady=(2, 0))

    def set_distance(value: str) -> None:
        try:
            distance_value = float(value)
        except ValueError:
            return
        state.stamp_distance_limit_percent = max(0.0, min(100.0, distance_value))

    admin_theme.create_scale(
        distance_card,
        variable=distance_var,
        from_=0,
        to=100,
        resolution=1,
        command=set_distance,
        background=admin_theme.SURFACE_BG,
    ).pack(fill="x", pady=(4, 0))

    def set_lifetime(value: str) -> None:
        try:
            lifetime_value = float(value)
        except ValueError:
            return
        state.stamp_lifetime_sec = max(0.1, lifetime_value)

    admin_theme.create_scale(
        lifetime_card,
        variable=lifetime_var,
        from_=0.5,
        to=60.0,
        resolution=0.5,
        command=set_lifetime,
        background=admin_theme.SURFACE_BG,
    ).pack(fill="x", pady=(4, 0))

    actions = tk.Frame(actions_card, bg=admin_theme.SURFACE_BG)
    actions.pack(fill="x", pady=(4, 0))

    def reset_defaults() -> None:
        state.reset_stamp_experiment_settings()
        speed_min_var.set(state.stamp_speed_min_px_s)
        speed_max_var.set(state.stamp_speed_max_px_s)
        distance_var.set(state.stamp_distance_limit_percent)
        lifetime_var.set(state.stamp_lifetime_sec)

    admin_theme.create_button(
        actions,
        text="デフォルトに戻す",
        command=reset_defaults,
        variant="secondary",
    ).pack(side="left")
    admin_theme.create_button(
        actions,
        text="閉じる",
        command=on_close,
        variant="primary",
    ).pack(side="right")


def create_menu_window(
    switch_display_callback: Callable[[], None],
    refresh_layout_callback: Callable[[], None],
    root_ref: tk.Tk,
) -> None:
    menu = tk.Toplevel(root_ref)
    menu.title("コントローラーメニュー")

    wrapper = admin_theme.create_window_shell(
        menu,
        geometry="430x420",
        topmost=True,
    )

    status_var = tk.StringVar(value="未接続")
    current_session_var = tk.StringVar(value="現在のセッション: なし")
    session_var = tk.StringVar(value="default")
    state.menu_status_var = status_var
    state.menu_current_session_var = current_session_var
    state.menu_session_var = session_var

    control_row = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    control_row.pack(fill="x")

    status_badge = admin_theme.create_badge(control_row, textvariable=status_var)
    status_badge.pack(side="left", padx=(0, 10))

    def refresh_status_badge(*_args: str) -> None:
        try:
            if status_badge.winfo_exists():
                admin_theme.update_badge(status_badge, status_var.get())
        except tk.TclError:
            return

    status_var.trace_add("write", refresh_status_badge)
    refresh_status_badge()

    admin_theme.create_entry(control_row, textvariable=session_var).pack(
        side="left",
        expand=True,
        fill="x",
    )

    admin_theme.create_button(
        control_row,
        text="接続",
        command=lambda: connect_session(session_var.get().strip()),
        variant="primary",
    ).pack(side="left", padx=(10, 0))

    buttons = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    buttons.pack(fill="both", expand=True, pady=(16, 0))

    _create_dashboard_button_row(
        buttons,
        left_text="ディスプレイ切替",
        left_command=switch_display_callback,
        right_text="実験",
        right_command=lambda: _open_experiment_window(root_ref, refresh_layout_callback),
    )
    _create_dashboard_button_row(
        buttons,
        left_text="コメント履歴",
        left_command=lambda: _open_history_window(root_ref),
        right_text="文字起こし履歴",
        right_command=lambda: _open_transcription_history_window(root_ref),
    )

    def export_dialog(fmt: str) -> None:
        if not state.message_log:
            messagebox.showinfo("保存", "データがありません")
            return
        try:
            import pandas as pd
        except ModuleNotFoundError:
            messagebox.showerror(
                "保存エラー",
                "履歴保存には pandas のインストールが必要です。",
            )
            return

        data_frame = pd.DataFrame(state.message_log).rename(
            columns={
                "real_name": "本名",
                "name": "名前",
                "text": "コメント",
                "time": "時間",
            }
        )
        if fmt == "xlsx":
            try:
                import openpyxl  # noqa: F401
            except ModuleNotFoundError:
                messagebox.showerror(
                    "保存エラー",
                    "Excel 保存には openpyxl のインストールが必要です。",
                )
                return
            path = filedialog.asksaveasfilename(
                defaultextension=".xlsx",
                filetypes=[("Excelファイル", "*.xlsx")],
                initialfile=_default_export_filename(".xlsx"),
            )
            if not path:
                return
            out = io.BytesIO()
            with pd.ExcelWriter(out, engine="openpyxl") as writer:
                data_frame.to_excel(writer, index=False, sheet_name="コメント履歴")
            with open(path, "wb") as file_obj:
                file_obj.write(out.getvalue())
        else:
            path = filedialog.asksaveasfilename(
                defaultextension=".csv",
                filetypes=[("CSVファイル", "*.csv")],
                initialfile=_default_export_filename(".csv"),
            )
            if not path:
                return
            data_frame.to_csv(path, index=False, encoding="utf-8-sig")
        messagebox.showinfo("保存", "保存しました")

    _create_dashboard_button_row(
        buttons,
        left_text="CSV で保存",
        left_command=lambda: export_dialog("csv"),
        right_text="Excel で保存",
        right_command=lambda: export_dialog("xlsx"),
    )

    def confirm_exit() -> None:
        if messagebox.askokcancel("終了", "アプリを終了しますか？"):
            disconnect_session(show_status=False)
            stop_transcription_service()
            root_ref.destroy()

    admin_theme.create_button(
        buttons,
        text="アプリ終了",
        command=confirm_exit,
        variant="danger",
    ).pack(fill="x", pady=(2, 0))
