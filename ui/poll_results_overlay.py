from __future__ import annotations

from collections.abc import Mapping

import tkinter as tk

from state import app_state as state
from ui.admin_cards import build_poll_results_view
from ui import admin_theme


def sync_poll_results_overlay(root: tk.Tk, results: Mapping[str, object] | None) -> None:
    if results is None:
        _destroy_overlay()
        return
    view = build_poll_results_view(results)
    win = state.poll_results_overlay_window
    if win is None or not _exists(win):
        win = tk.Toplevel(root)
        state.poll_results_overlay_window = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#111827")
    for child in win.winfo_children():
        child.destroy()

    card = tk.Frame(win, bg="#ffffff", padx=22, pady=20, highlightthickness=2)
    card.configure(highlightbackground="#111827", highlightcolor="#111827")
    card.pack(expand=True, fill="both", padx=2, pady=2)

    tk.Label(
        card,
        text="投票結果",
        bg="#ffffff",
        fg="#111827",
        font=("Yu Gothic UI", -20, "bold"),
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        card,
        text=view.question,
        bg="#ffffff",
        fg="#111827",
        font=("Yu Gothic UI", -14, "bold"),
        justify="left",
        anchor="w",
        wraplength=420,
        pady=8,
    ).pack(fill="x")
    tk.Label(
        card,
        text=f"回答率: {view.answer_rate_percent:.1f}%（{view.answer_count} / {view.delivered_count} 人）",
        bg="#ffffff",
        fg="#4b5563",
        font=admin_theme.SMALL_FONT,
        anchor="w",
    ).pack(fill="x", pady=(0, 12))

    chart = tk.Frame(card, bg="#ffffff")
    chart.pack(fill="x")
    max_count = max((option.count for option in view.options), default=0)
    for option in view.options:
        row = tk.Frame(chart, bg="#ffffff")
        row.pack(fill="x", pady=5)
        row.grid_columnconfigure(2, weight=1)
        tk.Label(
            row,
            text=option.label,
            bg="#ffffff",
            fg="#111827",
            font=admin_theme.SMALL_FONT,
            anchor="e",
            justify="right",
            width=14,
            wraplength=120,
        ).grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        tk.Frame(row, bg="#111827", width=2, height=28).grid(
            row=0, column=1, sticky="ns"
        )
        bar_area = tk.Frame(row, bg="#ffffff", height=28)
        bar_area.grid(row=0, column=2, sticky="ew", padx=(10, 0))
        width_ratio = (option.count / max_count) if max_count > 0 else 0.0
        bar = tk.Frame(bar_area, bg="#ffd8bd", highlightthickness=1)
        bar.configure(highlightbackground="#374151", highlightcolor="#374151")
        bar.place(relx=0, rely=0.14, relheight=0.72, relwidth=max(0.0, width_ratio))
        tk.Label(
            bar_area,
            text=f"{option.count}票 / {option.percentage:.1f}%",
            bg="#ffffff",
            fg="#111827",
            font=admin_theme.SMALL_BOLD_FONT,
            anchor="w",
        ).pack(fill="both", padx=8)

    win.update_idletasks()
    width = min(max(460, win.winfo_reqwidth()), max(460, root.winfo_width() - 24))
    height = min(max(280, win.winfo_reqheight()), max(280, root.winfo_height() - 24))
    left = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
    top = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 2)
    win.geometry(f"{width}x{height}+{left}+{top}")
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


def _exists(win: tk.Toplevel) -> bool:
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False
