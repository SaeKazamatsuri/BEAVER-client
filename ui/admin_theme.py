from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import tkinter as tk

WINDOW_BG = "#eef3f7"
SURFACE_BG = "#ffffff"
SURFACE_ALT_BG = "#f8fbff"
BORDER_COLOR = "#d7e2ec"
TITLE_COLOR = "#0f172a"
TEXT_COLOR = "#1e293b"
MUTED_TEXT_COLOR = "#64748b"
SUBTLE_TEXT_COLOR = "#475569"
INPUT_BORDER_COLOR = "#cbd5e1"
INPUT_BG = "#ffffff"
PRIMARY_BUTTON_BG = "#1d4ed8"
PRIMARY_BUTTON_ACTIVE_BG = "#1e40af"
PRIMARY_BUTTON_FG = "#ffffff"
SECONDARY_BUTTON_BG = "#e2e8f0"
SECONDARY_BUTTON_ACTIVE_BG = "#cbd5e1"
SECONDARY_BUTTON_FG = "#0f172a"
DANGER_BUTTON_BG = "#fee2e2"
DANGER_BUTTON_ACTIVE_BG = "#fecaca"
DANGER_BUTTON_FG = "#991b1b"
SCROLLBAR_BG = "#dbeafe"
SCROLLBAR_ACTIVE_BG = "#bfdbfe"
SCROLLBAR_TROUGH_BG = "#eef3f7"
RADIO_SELECT_COLOR = "#dbeafe"
SCALE_TROUGH_COLOR = "#dbeafe"
SCALE_ACTIVE_BG = "#1d4ed8"

WINDOW_TITLE_FONT = ("Yu Gothic UI", 18, "bold")
SECTION_TITLE_FONT = ("Yu Gothic UI", 13, "bold")
CARD_TITLE_FONT = ("Yu Gothic UI", 11, "bold")
BODY_FONT = ("Yu Gothic UI", 11)
SMALL_FONT = ("Yu Gothic UI", 10)
SMALL_BOLD_FONT = ("Yu Gothic UI", 9, "bold")
BUTTON_FONT = ("Yu Gothic UI", 10, "bold")
ENTRY_FONT = ("Yu Gothic UI", 11)

WINDOW_PAD = 16
CARD_PAD_X = 18
CARD_PAD_Y = 16

ButtonVariant = Literal["primary", "secondary", "danger"]


@dataclass(frozen=True, slots=True)
class BadgePalette:
    foreground: str
    background: str


@dataclass(frozen=True, slots=True)
class ListCardPalette:
    accent: str
    tag_background: str
    card_background: str


def get_badge_palette(label: str) -> BadgePalette:
    palette = {
        "未接続": BadgePalette(foreground="#475569", background="#e2e8f0"),
        "起動中": BadgePalette(foreground="#9a3412", background="#ffedd5"),
        "待機中": BadgePalette(foreground="#1d4ed8", background="#dbeafe"),
        "稼働中": BadgePalette(foreground="#047857", background="#d1fae5"),
        "異常": BadgePalette(foreground="#b91c1c", background="#fee2e2"),
        "停止": BadgePalette(foreground="#374151", background="#e5e7eb"),
        "接続中…": BadgePalette(foreground="#9a3412", background="#ffedd5"),
        "接続済み": BadgePalette(foreground="#047857", background="#d1fae5"),
        "再接続中…": BadgePalette(foreground="#1d4ed8", background="#dbeafe"),
        "接続失敗": BadgePalette(foreground="#b91c1c", background="#fee2e2"),
    }
    return palette.get(label, BadgePalette(foreground=TITLE_COLOR, background="#e2e8f0"))


def get_list_card_palette(kind: str) -> ListCardPalette:
    palette = {
        "comment": ListCardPalette(
            accent="#0f766e",
            tag_background="#ccfbf1",
            card_background=SURFACE_BG,
        ),
        "stamp": ListCardPalette(
            accent="#9a3412",
            tag_background="#ffedd5",
            card_background=SURFACE_ALT_BG,
        ),
        "transcription": ListCardPalette(
            accent="#0f766e",
            tag_background="#ccfbf1",
            card_background=SURFACE_BG,
        ),
        "status": ListCardPalette(
            accent="#1d4ed8",
            tag_background="#dbeafe",
            card_background=SURFACE_ALT_BG,
        ),
    }
    return palette.get(
        kind,
        ListCardPalette(
            accent="#1d4ed8",
            tag_background="#dbeafe",
            card_background=SURFACE_BG,
        ),
    )


def create_window_shell(
    window: tk.Toplevel,
    *,
    geometry: str,
    topmost: bool = False,
) -> tk.Frame:
    window.geometry(geometry)
    window.configure(bg=WINDOW_BG)
    if topmost:
        window.attributes("-topmost", True)
    wrapper = tk.Frame(window, bg=WINDOW_BG, padx=WINDOW_PAD, pady=WINDOW_PAD)
    wrapper.pack(expand=True, fill="both")
    return wrapper


def create_card(
    parent: tk.Misc,
    *,
    background: str = SURFACE_BG,
    padx: int = CARD_PAD_X,
    pady: int = CARD_PAD_Y,
) -> tk.Frame:
    return tk.Frame(
        parent,
        bg=background,
        highlightbackground=BORDER_COLOR,
        highlightthickness=1,
        bd=0,
        padx=padx,
        pady=pady,
    )


def create_badge(
    parent: tk.Misc,
    *,
    text: str | None = None,
    textvariable: tk.StringVar | None = None,
) -> tk.Label:
    badge_text = ""
    if textvariable is not None:
        badge_text = textvariable.get()
    elif text is not None:
        badge_text = text
    palette = get_badge_palette(badge_text)
    label = tk.Label(
        parent,
        bg=palette.background,
        fg=palette.foreground,
        padx=12,
        pady=4,
        font=SMALL_FONT,
    )
    if textvariable is not None:
        label.configure(textvariable=textvariable)
    else:
        label.configure(text=badge_text)
    return label


def update_badge(label: tk.Label, badge_text: str) -> None:
    palette = get_badge_palette(badge_text)
    label.configure(bg=palette.background, fg=palette.foreground)


def create_button(
    parent: tk.Misc,
    *,
    text: str,
    command: Callable[[], None],
    variant: ButtonVariant = "secondary",
) -> tk.Button:
    if variant == "primary":
        bg = PRIMARY_BUTTON_BG
        active_bg = PRIMARY_BUTTON_ACTIVE_BG
        fg = PRIMARY_BUTTON_FG
    elif variant == "danger":
        bg = DANGER_BUTTON_BG
        active_bg = DANGER_BUTTON_ACTIVE_BG
        fg = DANGER_BUTTON_FG
    else:
        bg = SECONDARY_BUTTON_BG
        active_bg = SECONDARY_BUTTON_ACTIVE_BG
        fg = SECONDARY_BUTTON_FG

    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active_bg,
        activeforeground=fg,
        relief="flat",
        bd=0,
        highlightthickness=0,
        cursor="hand2",
        font=BUTTON_FONT,
        padx=14,
        pady=10,
    )


def create_entry(
    parent: tk.Misc,
    *,
    textvariable: tk.StringVar,
) -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=textvariable,
        bg=INPUT_BG,
        fg=TEXT_COLOR,
        insertbackground=TEXT_COLOR,
        relief="flat",
        bd=0,
        highlightbackground=INPUT_BORDER_COLOR,
        highlightcolor=PRIMARY_BUTTON_BG,
        highlightthickness=1,
        font=ENTRY_FONT,
    )


def create_radiobutton(
    parent: tk.Misc,
    *,
    text: str,
    value: str,
    variable: tk.StringVar,
    command: Callable[[], None],
    background: str,
) -> tk.Radiobutton:
    return tk.Radiobutton(
        parent,
        text=text,
        value=value,
        variable=variable,
        command=command,
        bg=background,
        fg=TEXT_COLOR,
        activebackground=background,
        activeforeground=TEXT_COLOR,
        selectcolor=RADIO_SELECT_COLOR,
        disabledforeground=MUTED_TEXT_COLOR,
        font=BODY_FONT,
        anchor="w",
        relief="flat",
        bd=0,
        highlightthickness=0,
    )


def create_scale(
    parent: tk.Misc,
    *,
    variable: tk.DoubleVar,
    from_: float,
    to: float,
    resolution: float,
    command: Callable[[str], None],
    background: str,
) -> tk.Scale:
    return tk.Scale(
        parent,
        from_=from_,
        to=to,
        orient="horizontal",
        resolution=resolution,
        showvalue=True,
        variable=variable,
        command=command,
        bg=background,
        fg=TEXT_COLOR,
        activebackground=SCALE_ACTIVE_BG,
        highlightthickness=0,
        relief="flat",
        bd=0,
        troughcolor=SCALE_TROUGH_COLOR,
        font=SMALL_FONT,
    )


def create_scrollable_panel(
    parent: tk.Misc,
    *,
    background: str = WINDOW_BG,
) -> tuple[tk.Frame, tk.Frame]:
    container = tk.Frame(parent, bg=background)
    canvas = tk.Canvas(
        container,
        bg=background,
        highlightthickness=0,
        bd=0,
        relief="flat",
    )
    scrollbar = tk.Scrollbar(
        container,
        orient="vertical",
        command=canvas.yview,
        bg=SCROLLBAR_BG,
        activebackground=SCROLLBAR_ACTIVE_BG,
        troughcolor=SCROLLBAR_TROUGH_BG,
        relief="flat",
        bd=0,
        highlightthickness=0,
    )
    content = tk.Frame(canvas, bg=background)
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

    def _is_descendant(widget: object) -> bool:
        current = widget
        while isinstance(current, tk.Misc):
            if current == container:
                return True
            current = getattr(current, "master", None)
        return False

    def _scroll_units(delta: int) -> int:
        if delta == 0:
            return 0
        if abs(delta) >= 120:
            units = int(-delta / 120)
            if units != 0:
                return units
        return -1 if delta > 0 else 1

    def _on_mousewheel(event: tk.Event) -> str | None:
        if not container.winfo_exists() or not canvas.winfo_exists():
            return None
        if not _is_descendant(getattr(event, "widget", None)):
            return None
        delta = getattr(event, "delta", 0)
        if not isinstance(delta, int):
            return None
        units = _scroll_units(delta)
        if units == 0:
            return None
        canvas.yview_scroll(units, "units")
        return "break"

    def _on_mousewheel_linux(event: tk.Event) -> str | None:
        if not container.winfo_exists() or not canvas.winfo_exists():
            return None
        if not _is_descendant(getattr(event, "widget", None)):
            return None
        num = getattr(event, "num", 0)
        if num == 4:
            canvas.yview_scroll(-1, "units")
            return "break"
        if num == 5:
            canvas.yview_scroll(1, "units")
            return "break"
        return None

    toplevel = parent.winfo_toplevel()
    toplevel.bind("<MouseWheel>", _on_mousewheel, add="+")
    toplevel.bind("<Button-4>", _on_mousewheel_linux, add="+")
    toplevel.bind("<Button-5>", _on_mousewheel_linux, add="+")
    return container, content
