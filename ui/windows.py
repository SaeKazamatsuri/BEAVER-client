from __future__ import annotations

import io
import csv
import threading
from collections.abc import Callable, Sequence
from typing import Protocol

import tkinter as tk
from tkinter import filedialog, messagebox

from services.backend_api import (
    BackendApiError,
    create_poll,
    fetch_behavior_events,
    fetch_poll_results,
    fetch_polls,
    generate_sakura_names,
    post_sakura_comment,
    set_reaction_mode,
    set_poll_results_display,
    start_poll,
)
from services.events import connect_session, disconnect_session
from state import app_state as state
from ui.admin_cards import (
    CommentHistoryRow,
    PollResultsView,
    build_comment_history_rows,
    build_comment_history_signature,
    build_poll_results_view,
    string_value as _string_value,
)
from ui.file_utils import build_export_filename
from ui import admin_theme

try:
    import win32api
    import win32con
    import win32gui
except ModuleNotFoundError:
    win32api = None
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


class CommentWindowVisibilityTarget(Protocol):
    def withdraw(self) -> object:
        ...

    def deiconify(self) -> object:
        ...

    def attributes(self, *args: object) -> object:
        ...

    def winfo_id(self) -> int:
        ...


def _default_export_filename(extension: str) -> str:
    session_name = _string_value(getattr(state, "CURRENT_SESSION", "")).strip()
    if not session_name:
        menu_session_var = state.menu_session_var
        if menu_session_var is not None:
            session_name = menu_session_var.get().strip()
    return build_export_filename(session_name, extension)


def _comment_toggle_button_text(hidden: bool) -> str:
    if hidden:
        return "コメント欄再表示"
    return "コメント欄非表示"


def toggle_comment_window_visibility(
    target: CommentWindowVisibilityTarget,
    *,
    hidden: bool,
    refresh_layout_callback: Callable[[], None],
) -> bool:
    if hidden:
        refresh_layout_callback()
        target.deiconify()
        try:
            target.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            set_always_on_top(target.winfo_id())
        except (tk.TclError, RuntimeError):
            pass
        return False

    target.withdraw()
    return True


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

        if entry.bookmarks > 0:
            tk.Label(
                row,
                text=f"🔖 {entry.bookmarks}",
                bg=admin_theme.WINDOW_BG,
                fg=admin_theme.TITLE_COLOR,
                font=admin_theme.SMALL_BOLD_FONT,
                anchor="e",
            ).grid(row=0, column=3, sticky="ne", padx=(10, 0))

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

    last_signature: list[object] = [None]

    def refresh() -> None:
        if not win.winfo_exists():
            return

        snapshot = list(state.message_log)
        order = state.display_order
        signature = (build_comment_history_signature(snapshot), order)
        if signature != last_signature[0]:
            rows = build_comment_history_rows(snapshot, order=order)
            count_var.set(f"表示件数: {len(rows)} 件")
            _render_comment_history_rows(
                content,
                rows,
                empty_message="まだテキストコメント履歴はありません。",
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


# === アンケート（poll）===


def _current_session_name() -> str:
    session = _string_value(getattr(state, "CURRENT_SESSION", "")).strip()
    if session:
        return session
    menu_session_var = state.menu_session_var
    if menu_session_var is not None:
        candidate = menu_session_var.get().strip()
        if candidate:
            return candidate
    return "default"


def _show_async_error(root_ref: tk.Tk, message: str) -> None:
    def show() -> None:
        try:
            messagebox.showerror("アンケート", message)
        except Exception:
            pass

    try:
        root_ref.after(0, show)
    except Exception:
        pass


def _center_window_on_monitor(win: tk.Toplevel, anchor: tk.Misc) -> None:
    """コメントオーバーレイ（anchor）と同じモニタの中央へ配置する。"""
    win.update_idletasks()
    width = win.winfo_width() or win.winfo_reqwidth()
    height = win.winfo_height() or win.winfo_reqheight()

    try:
        anchor_x = anchor.winfo_rootx()
        anchor_y = anchor.winfo_rooty()
        anchor_w = anchor.winfo_width()
        anchor_h = anchor.winfo_height()
    except Exception:
        anchor_x = anchor_y = 0
        anchor_w = win.winfo_screenwidth()
        anchor_h = win.winfo_screenheight()

    left = anchor_x + (anchor_w - width) // 2
    top = anchor_y + (anchor_h - height) // 2

    if win32api is not None and win32con is not None:
        try:
            monitor = win32api.MonitorFromWindow(
                anchor.winfo_id(), win32con.MONITOR_DEFAULTTONEAREST
            )
            info = win32api.GetMonitorInfo(monitor)
            area = info.get("Work") or info.get("Monitor")
            if area is not None:
                mon_left, mon_top, mon_right, mon_bottom = area
                left = mon_left + ((mon_right - mon_left) - width) // 2
                top = mon_top + ((mon_bottom - mon_top) - height) // 2
        except Exception:
            pass

    win.geometry(f"{width}x{height}+{int(left)}+{int(top)}")


def _render_poll_list(
    parent: tk.Frame,
    polls: Sequence[dict[str, object]],
    *,
    root_ref: tk.Tk,
    session: str,
    on_start: Callable[[int], None],
    on_results: Callable[[int], None],
    on_display: Callable[[int, str], None],
) -> None:
    for child in parent.winfo_children():
        child.destroy()

    if not polls:
        tk.Label(
            parent,
            text="まだアンケートは登録されていません。",
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.SUBTLE_TEXT_COLOR,
            justify="left",
            wraplength=560,
            anchor="w",
            padx=8,
            pady=16,
            font=admin_theme.BODY_FONT,
        ).pack(fill="x")
        return

    for poll in polls:
        poll_id = poll.get("id")
        if not isinstance(poll_id, int):
            continue
        options = poll.get("options")
        option_labels = (
            [str(option) for option in options] if isinstance(options, list) else []
        )
        duration = poll.get("duration_sec")
        duration_text = f"{duration} 秒" if isinstance(duration, int) else "-"

        card = admin_theme.create_card(parent)
        card.pack(fill="x", padx=8, pady=6)

        tk.Label(
            card,
            text=_string_value(poll.get("question")) or "-",
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.TITLE_COLOR,
            font=admin_theme.CARD_TITLE_FONT,
            justify="left",
            anchor="w",
            wraplength=520,
        ).pack(fill="x")

        tk.Label(
            card,
            text="／".join(option_labels) if option_labels else "-",
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            justify="left",
            anchor="w",
            wraplength=520,
            pady=4,
        ).pack(fill="x")

        tk.Label(
            card,
            text=f"制限時間: {duration_text}",
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.MUTED_TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            anchor="w",
        ).pack(fill="x")

        actions = tk.Frame(card, bg=admin_theme.SURFACE_BG)
        actions.pack(fill="x", pady=(8, 0))
        admin_theme.create_button(
            actions,
            text="開始（配信）",
            command=lambda pid=poll_id: on_start(pid),
            variant="primary",
        ).pack(side="left", expand=True, fill="x")
        admin_theme.create_button(
            actions,
            text="集計",
            command=lambda pid=poll_id: on_results(pid),
            variant="secondary",
        ).pack(side="left", expand=True, fill="x", padx=(10, 0))

        display_actions = tk.Frame(card, bg=admin_theme.SURFACE_BG)
        display_actions.pack(fill="x", pady=(8, 0))
        for label, target in (
            ("フロント表示", "frontend"),
            ("クライアント表示", "client"),
            ("両方表示", "both"),
            ("非表示", "none"),
        ):
            admin_theme.create_button(
                display_actions,
                text=label,
                command=lambda pid=poll_id, t=target: on_display(pid, t),
                variant="secondary",
            ).pack(side="left", expand=True, fill="x", padx=(0, 6))


def _open_poll_window(root_ref: tk.Tk) -> None:
    if _focus_existing_window(state.poll_window):
        return

    win = tk.Toplevel(root_ref)
    state.poll_window = win
    win.title("アンケート")

    def on_close() -> None:
        try:
            win.destroy()
        finally:
            state.poll_window = None

    win.protocol("WM_DELETE_WINDOW", on_close)

    wrapper = admin_theme.create_window_shell(win, geometry="640x780", topmost=True)
    _create_window_header(
        wrapper,
        title="アンケート",
        description="質問と選択肢（2〜4個）を登録し、接続中のユーザーへ配信できます。配信後は集計で結果を確認できます。",
        wraplength=560,
    )

    form = _create_titled_card(
        wrapper,
        title="質問を登録",
        description="選択肢は2〜4個（空欄は無視）。制限時間内に未回答だと回答側は自動で閉じます。",
        wraplength=560,
    )

    question_var = tk.StringVar()
    tk.Label(
        form,
        text="質問文",
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(6, 0))
    admin_theme.create_entry(form, textvariable=question_var).pack(
        fill="x", pady=(2, 8)
    )

    option_vars = [tk.StringVar() for _ in range(4)]
    for index, option_var in enumerate(option_vars):
        tk.Label(
            form,
            text=f"選択肢{index + 1}",
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            anchor="w",
        ).pack(fill="x")
        admin_theme.create_entry(form, textvariable=option_var).pack(
            fill="x", pady=(2, 6)
        )

    duration_var = tk.DoubleVar(value=20.0)
    tk.Label(
        form,
        text="制限時間（秒）",
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(4, 0))
    admin_theme.create_scale(
        form,
        variable=duration_var,
        from_=5,
        to=120,
        resolution=1,
        command=lambda _value: None,
        background=admin_theme.SURFACE_BG,
    ).pack(fill="x", pady=(2, 6))

    list_frame, list_content = admin_theme.create_scrollable_panel(
        wrapper,
        background=admin_theme.WINDOW_BG,
    )

    def start_poll_action(poll_id: int) -> None:
        session = _current_session_name()

        def worker() -> None:
            try:
                start_poll(session, poll_id)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - ネットワーク例外を UI に伝える
                _show_async_error(root_ref, str(exc))
                return
            root_ref.after(
                0, lambda: messagebox.showinfo("アンケート", "配信しました。")
            )

        threading.Thread(target=worker, daemon=True).start()

    def open_results(poll_id: int) -> None:
        _open_poll_results_window(root_ref, poll_id, _current_session_name())

    def display_results(poll_id: int, target: str) -> None:
        session = _current_session_name()

        def worker() -> None:
            try:
                set_poll_results_display(session, poll_id, target)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return
            message = "非表示にしました。" if target == "none" else "結果表示を更新しました。"
            root_ref.after(0, lambda: messagebox.showinfo("アンケート", message))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_list() -> None:
        session = _current_session_name()

        def worker() -> None:
            try:
                polls = fetch_polls(session)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return

            def apply() -> None:
                if not win.winfo_exists():
                    return
                _render_poll_list(
                    list_content,
                    polls,
                    root_ref=root_ref,
                    session=session,
                    on_start=start_poll_action,
                    on_results=open_results,
                    on_display=display_results,
                )

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def submit() -> None:
        question = question_var.get().strip()
        options = [
            option_var.get().strip()
            for option_var in option_vars
            if option_var.get().strip()
        ]
        duration = int(round(float(duration_var.get())))
        if not question:
            messagebox.showinfo("アンケート", "質問文を入力してください。")
            return
        if len(options) < 2:
            messagebox.showinfo("アンケート", "選択肢を2個以上入力してください。")
            return
        session = _current_session_name()

        def worker() -> None:
            try:
                create_poll(session, question, options, duration)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return

            def apply() -> None:
                if not win.winfo_exists():
                    return
                question_var.set("")
                for option_var in option_vars:
                    option_var.set("")
                refresh_list()

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    admin_theme.create_button(
        form,
        text="登録",
        command=submit,
        variant="primary",
    ).pack(fill="x", pady=(4, 0))

    list_header = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    list_header.pack(fill="x", pady=(12, 0))
    tk.Label(
        list_header,
        text="登録済みアンケート",
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.SECTION_TITLE_FONT,
        anchor="w",
    ).pack(side="left")
    admin_theme.create_button(
        list_header,
        text="更新",
        command=refresh_list,
        variant="secondary",
    ).pack(side="right")

    list_frame.pack(expand=True, fill="both", pady=(8, 0))

    refresh_list()


def _render_poll_results(content: tk.Frame, view: PollResultsView) -> None:
    for child in content.winfo_children():
        child.destroy()

    tk.Label(
        content,
        text=view.question,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.SECTION_TITLE_FONT,
        justify="left",
        anchor="w",
        wraplength=460,
    ).pack(fill="x", pady=(0, 8))

    average_text = (
        f"{view.average_response_sec:.1f} 秒"
        if view.average_response_sec is not None
        else "-"
    )
    tk.Label(
        content,
        text=(
            f"回答率: {view.answer_rate_percent:.1f}%"
            f"（{view.answer_count} / {view.delivered_count} 人）"
            f"　平均回答時間: {average_text}"
        ),
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.SUBTLE_TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        justify="left",
        anchor="w",
        wraplength=460,
    ).pack(fill="x", pady=(0, 10))

    for option in view.options:
        card = admin_theme.create_card(content, pady=10)
        card.pack(fill="x", pady=4)
        tk.Label(
            card,
            text=option.label,
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.TITLE_COLOR,
            font=admin_theme.CARD_TITLE_FONT,
            justify="left",
            anchor="w",
            wraplength=420,
        ).pack(fill="x")
        tk.Label(
            card,
            text=f"{option.count} 票 ／ {option.percentage:.1f}%",
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            anchor="w",
        ).pack(fill="x", pady=(2, 4))
        track = tk.Frame(card, bg="#e2e8f0", height=10)
        track.pack(fill="x")
        fill = tk.Frame(track, bg=admin_theme.PRIMARY_BUTTON_BG, height=10)
        fill.place(x=0, y=0, relheight=1.0, relwidth=min(1.0, option.percentage / 100.0))

    tk.Label(
        content,
        text="回答者",
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.SECTION_TITLE_FONT,
        anchor="w",
    ).pack(fill="x", pady=(12, 4))

    if not view.answers:
        tk.Label(
            content,
            text="まだ回答はありません。",
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.SUBTLE_TEXT_COLOR,
            font=admin_theme.BODY_FONT,
            anchor="w",
            padx=8,
            pady=8,
        ).pack(fill="x")
        return

    for answer in view.answers:
        row = tk.Frame(content, bg=admin_theme.WINDOW_BG, padx=6, pady=3)
        row.pack(fill="x")
        row.grid_columnconfigure(1, weight=1)
        tk.Label(
            row,
            text=answer.name,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.TITLE_COLOR,
            font=admin_theme.SMALL_BOLD_FONT,
            anchor="w",
            width=14,
        ).grid(row=0, column=0, sticky="nw", padx=(0, 8))
        tk.Label(
            row,
            text=answer.option_label,
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.TEXT_COLOR,
            font=admin_theme.BODY_FONT,
            justify="left",
            anchor="w",
            wraplength=300,
        ).grid(row=0, column=1, sticky="nsew")
        tk.Label(
            row,
            text=f"{answer.response_sec:.1f}s",
            bg=admin_theme.WINDOW_BG,
            fg=admin_theme.MUTED_TEXT_COLOR,
            font=admin_theme.SMALL_FONT,
            anchor="e",
        ).grid(row=0, column=2, sticky="ne", padx=(8, 0))


def _open_poll_results_window(root_ref: tk.Tk, poll_id: int, session: str) -> None:
    # 別ポールの集計を開く場合は、既存の集計ウィンドウを作り直す。
    existing = state.poll_results_window
    if existing is not None:
        try:
            if existing.winfo_exists():
                existing.destroy()
        except Exception:
            pass
        state.poll_results_window = None

    win = tk.Toplevel(root_ref)
    state.poll_results_window = win
    win.title("アンケート集計")
    win.configure(bg=admin_theme.WINDOW_BG)
    win.geometry("520x680")
    win.attributes("-topmost", True)

    def on_close() -> None:
        try:
            win.destroy()
        finally:
            state.poll_results_window = None

    win.protocol("WM_DELETE_WINDOW", on_close)

    wrapper = tk.Frame(win, bg=admin_theme.WINDOW_BG, padx=16, pady=16)
    wrapper.pack(expand=True, fill="both")

    status_var = tk.StringVar(value="読み込み中…")
    header = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    header.pack(fill="x")
    tk.Label(
        header,
        text="アンケート集計",
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TITLE_COLOR,
        font=admin_theme.WINDOW_TITLE_FONT,
        anchor="w",
    ).pack(side="left")
    tk.Label(
        wrapper,
        textvariable=status_var,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.SUBTLE_TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(4, 0))

    results_frame, content = admin_theme.create_scrollable_panel(
        wrapper,
        background=admin_theme.WINDOW_BG,
    )
    results_frame.pack(expand=True, fill="both", pady=(8, 0))

    def refresh() -> None:
        status_var.set("読み込み中…")

        def worker() -> None:
            try:
                results = fetch_poll_results(poll_id, session=session)
            except BackendApiError as exc:
                message = str(exc)
                root_ref.after(0, lambda: status_var.set(message))
                return
            except Exception as exc:  # noqa: BLE001
                message = str(exc)
                root_ref.after(0, lambda: status_var.set(message))
                return
            view = build_poll_results_view(results)

            def apply() -> None:
                if not win.winfo_exists():
                    return
                status_var.set("最終更新を反映しました（リアルタイム更新なし）。")
                _render_poll_results(content, view)

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    buttons = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    buttons.pack(fill="x", pady=(10, 0))
    admin_theme.create_button(
        buttons,
        text="更新",
        command=refresh,
        variant="primary",
    ).pack(side="left", expand=True, fill="x")
    admin_theme.create_button(
        buttons,
        text="閉じる",
        command=on_close,
        variant="secondary",
    ).pack(side="left", expand=True, fill="x", padx=(10, 0))

    refresh()
    _center_window_on_monitor(win, root_ref)
    win.after(50, lambda: _safe_set_topmost(win))


def _safe_set_topmost(win: tk.Toplevel) -> None:
    try:
        if win.winfo_exists():
            set_always_on_top(win.winfo_id())
    except (tk.TclError, RuntimeError):
        pass


def _display_order_button_text(order: str) -> str:
    # 押すと反対の並びに切り替わるので、現在の並びとは逆のラベルを出す。
    return "時系列順に表示" if order == "bookmark" else "リアクション順に表示"


def _open_reaction_mode_window(root_ref: tk.Tk) -> None:
    win = tk.Toplevel(root_ref)
    win.title("リアクション方式")
    wrapper = admin_theme.create_window_shell(win, geometry="420x260", topmost=True)
    _create_window_header(
        wrapper,
        title="リアクション方式",
        description="現在のセッションに対して、参加者画面のリアクションボタン構成を切り替えます。",
        wraplength=360,
    )
    status_var = tk.StringVar(value="")
    mode_var = tk.StringVar(value=state.reaction_mode)

    current_label = tk.Label(
        wrapper,
        text="",
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.BODY_FONT,
        anchor="w",
        justify="left",
        wraplength=360,
    )
    current_label.pack(fill="x", pady=(8, 0))

    def sync_current_label() -> None:
        _generation, mode, reaction_types = state.snapshot_reaction_mode()
        labels = " / ".join(
            f"{item.get('emoji', '')}{item.get('label', '')}" for item in reaction_types
        )
        mode_label = "1ボタン方式" if mode == "single_thumb" else "5ボタン方式"
        current_label.configure(text=f"現在: {mode_label}\n{labels}")

    sync_current_label()

    body = admin_theme.create_card(wrapper)
    body.pack(fill="x", pady=(10, 0))
    for label, value in (("1ボタン方式", "single_thumb"), ("5ボタン方式", "five_buttons")):
        tk.Radiobutton(
            body,
            text=label,
            variable=mode_var,
            value=value,
            bg=admin_theme.SURFACE_BG,
            fg=admin_theme.TEXT_COLOR,
            selectcolor=admin_theme.SURFACE_BG,
            activebackground=admin_theme.SURFACE_BG,
            font=admin_theme.BODY_FONT,
            anchor="w",
        ).pack(fill="x", pady=2)

    operator_var = tk.StringVar(value="admin")
    tk.Label(
        body,
        text="実操作者名",
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(8, 0))
    admin_theme.create_entry(body, textvariable=operator_var).pack(fill="x")

    def apply_mode() -> None:
        mode = mode_var.get()
        if not messagebox.askokcancel("リアクション方式", "リアクション方式を切り替えますか？"):
            return
        session = _current_session_name()
        operator = operator_var.get().strip() or "admin"

        def worker() -> None:
            try:
                result = set_reaction_mode(session, mode, operator)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return

            def apply() -> None:
                reaction_types = result.get("reaction_types")
                result_mode = result.get("mode")
                if isinstance(result_mode, str) and isinstance(reaction_types, list):
                    state.set_reaction_mode(result_mode, reaction_types)
                sync_current_label()
                status_var.set("更新しました。")

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    admin_theme.create_button(
        wrapper,
        text="切り替え",
        command=apply_mode,
        variant="primary",
    ).pack(fill="x", pady=(10, 0))
    tk.Label(
        wrapper,
        textvariable=status_var,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.SUBTLE_TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(6, 0))


def _participant_names_from_history() -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for message in state.message_log:
        name = _string_value(message.get("name")).strip()
        if not name or name in seen or message.get("source") == "sakura":
            continue
        seen.add(name)
        names.append(name)
    return names


def _open_sakura_window(root_ref: tk.Tk) -> None:
    win = tk.Toplevel(root_ref)
    win.title("サクラコメント")
    wrapper = admin_theme.create_window_shell(win, geometry="520x620", topmost=True)
    _create_window_header(
        wrapper,
        title="サクラコメント",
        description="選択した名義で通常コメントとして投稿します。研究ログにはサクラ投稿として記録されます。",
        wraplength=460,
    )

    candidate_var = tk.StringVar(value="")
    operator_var = tk.StringVar(value="admin")
    text_widget: tk.Text
    status_var = tk.StringVar(value="")

    names_card = _create_titled_card(wrapper, title="参加者ニックネーム")
    participant_list = tk.Listbox(
        names_card,
        height=5,
        bg="#ffffff",
        fg=admin_theme.TEXT_COLOR,
        activestyle="none",
    )
    participant_list.pack(fill="x", pady=(6, 0))

    def refresh_participants() -> None:
        participant_list.delete(0, tk.END)
        for name in _participant_names_from_history():
            participant_list.insert(tk.END, name)

    refresh_participants()

    candidate_card = _create_titled_card(wrapper, title="投稿名義")
    admin_theme.create_entry(candidate_card, textvariable=candidate_var).pack(fill="x", pady=(4, 6))

    candidate_buttons = tk.Frame(candidate_card, bg=admin_theme.SURFACE_BG)
    candidate_buttons.pack(fill="x")

    def choose_candidate(name: str) -> None:
        candidate_var.set(name)

    def generate_candidates() -> None:
        session = _current_session_name()
        names = _participant_names_from_history()
        status_var.set("候補生成中…")

        def worker() -> None:
            try:
                candidates = generate_sakura_names(session, names)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return

            def apply() -> None:
                for child in candidate_buttons.winfo_children():
                    child.destroy()
                for candidate in candidates:
                    admin_theme.create_button(
                        candidate_buttons,
                        text=candidate,
                        command=lambda value=candidate: choose_candidate(value),
                        variant="secondary",
                    ).pack(side="left", expand=True, fill="x", padx=(0, 6))
                if candidates:
                    candidate_var.set(candidates[0])
                status_var.set("候補を生成しました。")

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    admin_theme.create_button(
        candidate_card,
        text="GPTで候補を生成",
        command=generate_candidates,
        variant="secondary",
    ).pack(fill="x", pady=(8, 0))

    operator_card = _create_titled_card(wrapper, title="実操作者")
    admin_theme.create_entry(operator_card, textvariable=operator_var).pack(fill="x", pady=(4, 0))

    text_card = _create_titled_card(wrapper, title="本文")
    text_widget = tk.Text(
        text_card,
        height=7,
        wrap="word",
        bg="#ffffff",
        fg=admin_theme.TEXT_COLOR,
        insertbackground=admin_theme.TEXT_COLOR,
        font=admin_theme.BODY_FONT,
        relief="solid",
        borderwidth=1,
    )
    text_widget.pack(fill="both", expand=True, pady=(4, 0))

    def submit() -> None:
        display_name = candidate_var.get().strip()
        operator_name = operator_var.get().strip() or "admin"
        text = text_widget.get("1.0", "end").strip()
        if not display_name:
            messagebox.showinfo("サクラコメント", "投稿名義を入力してください。")
            return
        if not text:
            messagebox.showinfo("サクラコメント", "本文を入力してください。")
            return
        session = _current_session_name()
        status_var.set("送信中…")

        def worker() -> None:
            try:
                post_sakura_comment(session, display_name, text, operator_name)
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return

            def apply() -> None:
                text_widget.delete("1.0", "end")
                status_var.set("送信しました。")

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    admin_theme.create_button(
        wrapper,
        text="サクラコメントを送信",
        command=submit,
        variant="primary",
    ).pack(fill="x", pady=(10, 0))
    tk.Label(
        wrapper,
        textvariable=status_var,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.SUBTLE_TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(6, 0))


def _payload_summary(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key, value in payload.items():
        if len(parts) >= 4:
            break
        parts.append(f"{key}={value}")
    return ", ".join(parts)


def _open_behavior_events_window(root_ref: tk.Tk) -> None:
    win = tk.Toplevel(root_ref)
    win.title("トラッキングログ")
    wrapper = admin_theme.create_window_shell(win, geometry="900x640", topmost=True)
    _create_window_header(
        wrapper,
        title="トラッキングログ",
        description="最新の行動ログを確認します。WebSocketで届いたイベントは自動で反映されます。",
        wraplength=820,
    )

    controls = admin_theme.create_card(wrapper)
    controls.pack(fill="x", pady=(8, 0))
    event_type_var = tk.StringVar(value="")
    actor_var = tk.StringVar(value="")
    auto_refresh_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(value="")

    row = tk.Frame(controls, bg=admin_theme.SURFACE_BG)
    row.pack(fill="x")
    tk.Label(row, text="イベント種別", bg=admin_theme.SURFACE_BG, fg=admin_theme.TEXT_COLOR).pack(side="left")
    admin_theme.create_entry(row, textvariable=event_type_var).pack(side="left", fill="x", expand=True, padx=(8, 12))
    tk.Label(row, text="本名", bg=admin_theme.SURFACE_BG, fg=admin_theme.TEXT_COLOR).pack(side="left")
    admin_theme.create_entry(row, textvariable=actor_var).pack(side="left", fill="x", expand=True, padx=(8, 12))
    tk.Checkbutton(
        row,
        text="自動更新",
        variable=auto_refresh_var,
        bg=admin_theme.SURFACE_BG,
        fg=admin_theme.TEXT_COLOR,
        selectcolor=admin_theme.SURFACE_BG,
        activebackground=admin_theme.SURFACE_BG,
    ).pack(side="left")

    table_frame = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    table_frame.pack(expand=True, fill="both", pady=(10, 0))
    table_frame.grid_columnconfigure(0, weight=0)
    table_frame.grid_columnconfigure(1, weight=0)
    table_frame.grid_columnconfigure(2, weight=0)
    table_frame.grid_columnconfigure(3, weight=0)
    table_frame.grid_columnconfigure(4, weight=0)
    table_frame.grid_columnconfigure(5, weight=0)
    table_frame.grid_columnconfigure(6, weight=1)

    def render(events: Sequence[dict[str, object]]) -> None:
        for child in table_frame.winfo_children():
            child.destroy()
        headers = ("発生時刻", "表示名", "本名", "イベント", "対象", "ID", "payload")
        for col, header in enumerate(headers):
            tk.Label(
                table_frame,
                text=header,
                bg=admin_theme.WINDOW_BG,
                fg=admin_theme.TITLE_COLOR,
                font=admin_theme.SMALL_BOLD_FONT,
                anchor="w",
            ).grid(row=0, column=col, sticky="ew", padx=4, pady=(0, 4))
        for row_index, event in enumerate(events[:100], start=1):
            values = (
                _string_value(event.get("occurred_at")),
                _string_value(event.get("actor_name")),
                _string_value(event.get("actor_real_name")),
                _string_value(event.get("event_type")),
                _string_value(event.get("target_type")),
                _string_value(event.get("target_id")),
                _payload_summary(event.get("payload")),
            )
            for col, value in enumerate(values):
                tk.Label(
                    table_frame,
                    text=value,
                    bg=admin_theme.WINDOW_BG,
                    fg=admin_theme.TEXT_COLOR,
                    font=admin_theme.SMALL_FONT,
                    anchor="w",
                    justify="left",
                    wraplength=260 if col == 6 else 140,
                ).grid(row=row_index, column=col, sticky="nw", padx=4, pady=2)

    def refresh() -> None:
        session = _current_session_name()
        status_var.set("読み込み中…")

        def worker() -> None:
            try:
                events = fetch_behavior_events(
                    session,
                    limit=100,
                    event_type=event_type_var.get(),
                    actor_real_name=actor_var.get(),
                )
            except BackendApiError as exc:
                _show_async_error(root_ref, str(exc))
                return
            except Exception as exc:  # noqa: BLE001
                _show_async_error(root_ref, str(exc))
                return

            def apply() -> None:
                state.set_behavior_events(events)
                render(events)
                status_var.set(f"{len(events)}件を表示中")

            root_ref.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def export_csv() -> None:
        _generation, events = state.snapshot_behavior_events()
        if not events:
            messagebox.showinfo("トラッキングログ", "出力するログがありません。")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSVファイル", "*.csv")],
            initialfile=_default_export_filename("_behavior.csv"),
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow(["発生時刻", "表示名", "本名", "イベント", "対象", "ID", "payload"])
            for event in events:
                writer.writerow(
                    [
                        _string_value(event.get("occurred_at")),
                        _string_value(event.get("actor_name")),
                        _string_value(event.get("actor_real_name")),
                        _string_value(event.get("event_type")),
                        _string_value(event.get("target_type")),
                        _string_value(event.get("target_id")),
                        _payload_summary(event.get("payload")),
                    ]
                )
        messagebox.showinfo("トラッキングログ", "保存しました。")

    actions = tk.Frame(wrapper, bg=admin_theme.WINDOW_BG)
    actions.pack(fill="x", pady=(10, 0))
    admin_theme.create_button(actions, text="更新", command=refresh, variant="primary").pack(side="left")
    admin_theme.create_button(actions, text="CSV出力", command=export_csv, variant="secondary").pack(side="left", padx=(8, 0))
    tk.Label(
        actions,
        textvariable=status_var,
        bg=admin_theme.WINDOW_BG,
        fg=admin_theme.SUBTLE_TEXT_COLOR,
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(side="left", padx=(12, 0))

    last_generation = [-1]

    def poll_local_events() -> None:
        if not win.winfo_exists():
            return
        generation, events = state.snapshot_behavior_events()
        if auto_refresh_var.get() and generation != last_generation[0]:
            render(events)
            status_var.set(f"{len(events)}件を表示中")
            last_generation[0] = generation
        win.after(500, poll_local_events)

    refresh()
    poll_local_events()


def create_menu_window(
    switch_display_callback: Callable[[], None],
    refresh_layout_callback: Callable[[], None],
    root_ref: tk.Tk,
    set_display_order_callback: Callable[[str], None] | None = None,
) -> None:
    menu = tk.Toplevel(root_ref)
    menu.title("コントローラーメニュー")

    wrapper = admin_theme.create_window_shell(
        menu,
        geometry="430x620",
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
    admin_theme.create_button(
        buttons,
        text="コメント履歴",
        command=lambda: _open_history_window(root_ref),
        variant="secondary",
    ).pack(fill="x", pady=(0, 10))

    def toggle_display_order() -> None:
        next_order = "chronological" if state.display_order == "bookmark" else "bookmark"
        state.display_order = next_order
        if set_display_order_callback is not None:
            set_display_order_callback(next_order)
        if display_order_button.winfo_exists():
            display_order_button.configure(text=_display_order_button_text(next_order))

    display_order_button = admin_theme.create_button(
        buttons,
        text=_display_order_button_text(state.display_order),
        command=toggle_display_order,
        variant="secondary",
    )
    display_order_button.pack(fill="x", pady=(0, 10))

    admin_theme.create_button(
        buttons,
        text="アンケート",
        command=lambda: _open_poll_window(root_ref),
        variant="secondary",
    ).pack(fill="x", pady=(0, 10))

    _create_dashboard_button_row(
        buttons,
        left_text="リアクション方式",
        left_command=lambda: _open_reaction_mode_window(root_ref),
        right_text="サクラコメント",
        right_command=lambda: _open_sakura_window(root_ref),
    )

    admin_theme.create_button(
        buttons,
        text="トラッキングログ",
        command=lambda: _open_behavior_events_window(root_ref),
        variant="secondary",
    ).pack(fill="x", pady=(0, 10))

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
            root_ref.destroy()

    comment_window_hidden = [False]

    def toggle_comment_visibility() -> None:
        comment_window_hidden[0] = toggle_comment_window_visibility(
            root_ref,
            hidden=comment_window_hidden[0],
            refresh_layout_callback=refresh_layout_callback,
        )
        if toggle_comment_button.winfo_exists():
            toggle_comment_button.configure(
                text=_comment_toggle_button_text(comment_window_hidden[0])
            )

    toggle_comment_button = admin_theme.create_button(
        buttons,
        text=_comment_toggle_button_text(comment_window_hidden[0]),
        command=toggle_comment_visibility,
        variant="primary",
    )
    toggle_comment_button.pack(fill="x", pady=(2, 8))

    admin_theme.create_button(
        buttons,
        text="アプリ終了",
        command=confirm_exit,
        variant="danger",
    ).pack(fill="x", pady=(2, 0))
