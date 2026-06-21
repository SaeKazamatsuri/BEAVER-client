from __future__ import annotations

from collections.abc import Mapping

import tkinter as tk

from state import app_state as state
from ui.admin_cards import build_poll_results_view
from ui.display_layout import WindowRect

POLL_RESULTS_BG = "#f8fafc"
POLL_RESULTS_FG = "#111827"
POLL_RESULTS_MUTED_FG = "#475569"
POLL_RESULTS_BAR_BG = "#dbeafe"
POLL_RESULTS_BAR_FILL = "#f97316"
POLL_RESULTS_BORDER = "#0f172a"

_current_geometry: WindowRect | None = None


def sync_poll_results_overlay(root: tk.Tk, results: Mapping[str, object] | None) -> None:
    if results is None:
        _destroy_overlay()
        return
    view = build_poll_results_view(results)
    win = state.poll_results_overlay_window
    if win is None or not _exists(win):
        win = tk.Toplevel(root)
        state.poll_results_overlay_window = win
        win.title("アンケート結果")
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=POLL_RESULTS_BG)
    for child in win.winfo_children():
        child.destroy()

    body = tk.Frame(win, bg=POLL_RESULTS_BG, padx=56, pady=44)
    body.pack(expand=True, fill="both")

    tk.Label(
        body,
        text="アンケート結果",
        bg=POLL_RESULTS_BG,
        fg=POLL_RESULTS_FG,
        font=("Yu Gothic UI", -44, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        body,
        text=view.question,
        bg=POLL_RESULTS_BG,
        fg=POLL_RESULTS_FG,
        font=("Yu Gothic UI", -34, "bold"),
        justify="left",
        anchor="w",
        wraplength=max(520, _target_width(root) - 160),
    ).pack(fill="x", pady=(18, 10))
    tk.Label(
        body,
        text=f"回答率: {view.answer_rate_percent:.1f}%（{view.answer_count} / {view.delivered_count} 人）",
        bg=POLL_RESULTS_BG,
        fg=POLL_RESULTS_MUTED_FG,
        font=("Yu Gothic UI", -24, "bold"),
        anchor="w",
    ).pack(fill="x", pady=(0, 28))

    chart = tk.Frame(body, bg=POLL_RESULTS_BG)
    chart.pack(fill="x")
    max_count = max((option.count for option in view.options), default=0)
    for option in view.options:
        row = tk.Frame(chart, bg=POLL_RESULTS_BG)
        row.pack(fill="x", pady=13)
        row.grid_columnconfigure(2, weight=1)
        tk.Label(
            row,
            text=option.label,
            bg=POLL_RESULTS_BG,
            fg=POLL_RESULTS_FG,
            font=("Yu Gothic UI", -26, "bold"),
            anchor="e",
            justify="right",
            width=12,
            wraplength=260,
        ).grid(row=0, column=0, sticky="nsew", padx=(0, 22))
        tk.Frame(row, bg=POLL_RESULTS_BORDER, width=4, height=64).grid(
            row=0, column=1, sticky="ns"
        )
        width_ratio = (option.count / max_count) if max_count > 0 else 0.0
        bar_canvas = tk.Canvas(
            row,
            bg=POLL_RESULTS_BAR_BG,
            height=64,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
        )
        bar_canvas.grid(row=0, column=2, sticky="ew", padx=(20, 0))

        count_text = f"{option.count}票 / {option.percentage:.1f}%"

        def draw_bar(
            event: tk.Event,
            *,
            canvas: tk.Canvas = bar_canvas,
            ratio: float = width_ratio,
            text: str = count_text,
        ) -> None:
            width = max(1, int(event.width))
            canvas.delete("bar")
            canvas.create_rectangle(
                0,
                0,
                int(width * max(0.0, ratio)),
                64,
                fill=POLL_RESULTS_BAR_FILL,
                outline="",
                tags=("bar",),
            )
            canvas.create_text(
                18,
                32,
                text=text,
                fill=POLL_RESULTS_FG,
                font=("Yu Gothic UI", -24, "bold"),
                anchor="w",
                tags=("bar",),
            )

        bar_canvas.bind("<Configure>", draw_bar)

    win.update_idletasks()
    _apply_geometry(root, win)
    win.lift()


def update_poll_results_overlay_geometry(rect: WindowRect) -> None:
    global _current_geometry
    _current_geometry = rect
    win = state.poll_results_overlay_window
    if win is None or not _exists(win):
        return
    win.geometry(rect.to_geometry())
    win.lift()


def _destroy_overlay() -> None:
    win = state.poll_results_overlay_window
    state.poll_results_overlay_window = None
    if win is None:
        return
    try:
        if win.winfo_exists():
            win.destroy()
    except Exception:
        pass


def _target_width(root: tk.Tk) -> int:
    if _current_geometry is not None:
        return _current_geometry.width
    return max(900, root.winfo_width() * 3)


def _apply_geometry(root: tk.Tk, win: tk.Toplevel) -> None:
    if _current_geometry is not None:
        win.geometry(_current_geometry.to_geometry())
        return

    width = max(900, root.winfo_width() * 3)
    height = max(520, root.winfo_height())
    left = root.winfo_rootx() - width
    top = root.winfo_rooty()
    win.geometry(f"{width}x{height}+{left}+{top}")


def _exists(win: tk.Toplevel) -> bool:
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False
