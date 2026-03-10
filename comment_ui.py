from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SOFT_WRAP_MARKER = "\u200b"
LONG_TOKEN_PATTERN = re.compile(r"[0-9A-Za-z_./:-]{32,}")

COMMENT_COLUMN_BG = "#6dd3f7"
CARD_BG = "#ffffff"
CARD_BORDER = "#0b1f33"
CARD_SHADOW = "#5aaecb"
NAME_TAG_BG = "#ffef8a"
NAME_TAG_FG = "#0b1f33"
TIME_TEXT_FG = "#6b7a90"
BODY_TEXT_FG = "#0b1f33"
ACCENT_DOT_FILL = "#d6eef7"

NAME_FONT = ("Yu Gothic UI", 12, "bold")
TIME_FONT = ("Yu Gothic UI", 10)
BODY_FONT = ("Yu Gothic UI", 22, "bold")


@dataclass(frozen=True, slots=True)
class CommentEntry:
    id: int
    session: str
    name: str
    text: str
    time: str
    stamp_url: str | None
    created_at: str
    from_history: bool


def insert_soft_wraps(text: str, chunk: int = 16) -> str:
    def _split_match(match: re.Match[str]) -> str:
        token = match.group(0)
        parts = [token[index : index + chunk] for index in range(0, len(token), chunk)]
        return SOFT_WRAP_MARKER.join(parts)

    return LONG_TOKEN_PATTERN.sub(_split_match, text)


def comment_entry_from_message(message: Mapping[str, object]) -> CommentEntry | None:
    if _message_has_stamp(message):
        return None

    entry_id = message.get("id")
    if isinstance(entry_id, bool) or not isinstance(entry_id, int):
        return None

    session = _required_string(message.get("session"))
    name = _required_string(message.get("name"))
    text = _required_string(message.get("text"))
    time = _required_string(message.get("time"))
    created_at = _required_string(message.get("created_at"))
    if (
        session is None
        or name is None
        or text is None
        or time is None
        or created_at is None
    ):
        return None

    from_history = bool(message.get("_from_history", False))

    return CommentEntry(
        id=entry_id,
        session=session,
        name=name,
        text=text,
        time=time,
        stamp_url=None,
        created_at=created_at,
        from_history=from_history,
    )


def _message_has_stamp(message: Mapping[str, object]) -> bool:
    stamp_url = message.get("stamp_url")
    stamp = message.get("stamp")
    has_stamp_url = isinstance(stamp_url, str) and bool(stamp_url)
    has_stamp = isinstance(stamp, str) and bool(stamp)
    return has_stamp_url or has_stamp


def _required_string(value: object) -> str | None:
    if isinstance(value, str):
        return value
    return None


class CommentCardCanvas(tk.Canvas):
    def __init__(self, master: tk.Misc, entry: CommentEntry) -> None:
        super().__init__(
            master,
            background=COMMENT_COLUMN_BG,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
        )
        self._entry = entry
        self._last_width = 0
        self._last_height = 0
        self.bind("<Configure>", self._on_configure)
        self.after_idle(self._redraw)

    def _on_configure(self, _event: tk.Event) -> None:
        width = self.winfo_width()
        if width <= 1 or width == self._last_width:
            return
        self._last_width = width
        self._redraw()

    def _redraw(self) -> None:
        width = self.winfo_width()
        if width <= 1:
            self.after(10, self._redraw)
            return

        self.delete("all")

        card_left = 8
        card_top = 20
        card_right = max(card_left + 220, width - 8)
        card_inner_left = card_left + 26
        card_inner_right = card_right - 26
        label_x = card_left + 34
        label_y = 10
        time_y = card_top + 30
        body_y = card_top + 58
        body_width = max(120, card_inner_right - card_inner_left)
        body_text = insert_soft_wraps(self._entry.text)

        label_bbox, time_bbox, body_bbox = self._measure_text_bboxes(
            label_x=label_x,
            label_y=label_y,
            time_x=card_inner_right,
            time_y=time_y,
            body_x=card_inner_left,
            body_y=body_y,
            body_width=body_width,
            body_text=body_text,
        )

        card_bottom = max(card_top + 118, body_bbox[3] + 24, time_bbox[3] + 24)
        height = card_bottom + 20

        shadow_id = self._create_rounded_rectangle(
            card_left + 8,
            card_top + 12,
            card_right + 8,
            card_bottom + 12,
            radius=28,
            fill=CARD_SHADOW,
            outline="",
        )
        self._create_rounded_rectangle(
            card_left,
            card_top,
            card_right,
            card_bottom,
            radius=28,
            fill=CARD_BG,
            outline=CARD_BORDER,
            width=3,
        )

        dot_y = card_top + 28
        dot_x = card_right - 66
        for index in range(3):
            offset = index * 14
            self.create_oval(
                dot_x + offset,
                dot_y,
                dot_x + offset + 8,
                dot_y + 8,
                fill=ACCENT_DOT_FILL,
                outline="",
            )

        self._create_rounded_rectangle(
            label_bbox[0] - 14,
            label_bbox[1] - 8,
            label_bbox[2] + 14,
            label_bbox[3] + 8,
            radius=18,
            fill=NAME_TAG_BG,
            outline=CARD_BORDER,
            width=2,
        )

        self.create_text(
            label_x,
            label_y,
            anchor="w",
            fill=NAME_TAG_FG,
            font=NAME_FONT,
            text=self._entry.name,
        )
        self.create_text(
            card_inner_right,
            time_y,
            anchor="ne",
            fill=TIME_TEXT_FG,
            font=TIME_FONT,
            text=self._entry.time,
        )
        self.create_text(
            card_inner_left,
            body_y,
            anchor="nw",
            fill=BODY_TEXT_FG,
            font=BODY_FONT,
            justify="left",
            text=body_text,
            width=body_width,
        )

        self.tag_lower(shadow_id)
        if height != self._last_height:
            self._last_height = height
            self.configure(height=height)

    def _measure_text_bboxes(
        self,
        *,
        label_x: int,
        label_y: int,
        time_x: int,
        time_y: int,
        body_x: int,
        body_y: int,
        body_width: int,
        body_text: str,
    ) -> tuple[tuple[int, int, int, int], tuple[int, int, int, int], tuple[int, int, int, int]]:
        temp_label = self.create_text(
            label_x,
            label_y,
            anchor="w",
            fill=NAME_TAG_FG,
            font=NAME_FONT,
            text=self._entry.name,
        )
        temp_time = self.create_text(
            time_x,
            time_y,
            anchor="ne",
            fill=TIME_TEXT_FG,
            font=TIME_FONT,
            text=self._entry.time,
        )
        temp_body = self.create_text(
            body_x,
            body_y,
            anchor="nw",
            fill=BODY_TEXT_FG,
            font=BODY_FONT,
            justify="left",
            text=body_text,
            width=body_width,
        )

        label_bbox = self._bbox_or_default(
            temp_label,
            (label_x, label_y, label_x + 80, label_y + 24),
        )
        time_bbox = self._bbox_or_default(
            temp_time,
            (time_x - 80, time_y - 16, time_x, time_y + 4),
        )
        body_bbox = self._bbox_or_default(
            temp_body,
            (body_x, body_y, body_x + body_width, body_y + 40),
        )
        self.delete(temp_label)
        self.delete(temp_time)
        self.delete(temp_body)
        return label_bbox, time_bbox, body_bbox

    def _bbox_or_default(
        self,
        item_id: int,
        default: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        bbox = self.bbox(item_id)
        if bbox is None:
            return default
        return bbox

    def _create_rounded_rectangle(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        radius: int,
        **kwargs: object,
    ) -> int:
        points = [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1,
        ]
        return int(
            self.create_polygon(
                points,
                smooth=True,
                splinesteps=24,
                **kwargs,
            )
        )


class CommentListView(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, background=COMMENT_COLUMN_BG)
        self._cards: list[CommentCardCanvas] = []

        self._canvas = tk.Canvas(
            self,
            background=COMMENT_COLUMN_BG,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
        )
        self._canvas.pack(fill="both", expand=True)

        self._content = tk.Frame(self._canvas, background=COMMENT_COLUMN_BG)
        self._window_id = self._canvas.create_window((0, 0), window=self._content, anchor="nw")

        self._column = tk.Frame(self._content, background=COMMENT_COLUMN_BG)
        self._column.pack(fill="both", expand=True, padx=20, pady=(28, 40))

        self._content.bind("<Configure>", self._on_content_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", self._on_mousewheel_linux)
        self._canvas.bind("<Button-5>", self._on_mousewheel_linux)
        self._content.bind("<MouseWheel>", self._on_mousewheel)
        self._content.bind("<Button-4>", self._on_mousewheel_linux)
        self._content.bind("<Button-5>", self._on_mousewheel_linux)
        self._column.bind("<MouseWheel>", self._on_mousewheel)
        self._column.bind("<Button-4>", self._on_mousewheel_linux)
        self._column.bind("<Button-5>", self._on_mousewheel_linux)

    def clear(self) -> None:
        for card in self._cards:
            card.destroy()
        self._cards.clear()
        self.after_idle(self._refresh_scrollregion)

    def set_comments(self, comments: Sequence[CommentEntry]) -> None:
        self.clear()
        for comment in comments:
            self.add_comment(comment)

    def add_comment(self, comment: CommentEntry) -> None:
        card = CommentCardCanvas(self._column, comment)
        card.bind("<MouseWheel>", self._on_mousewheel)
        card.bind("<Button-4>", self._on_mousewheel_linux)
        card.bind("<Button-5>", self._on_mousewheel_linux)
        if self._cards:
            card.pack(fill="x", pady=(0, 16), before=self._cards[0])
        else:
            card.pack(fill="x", pady=(0, 16))
        self._cards.insert(0, card)
        self.after_idle(self._refresh_scrollregion)
        self.after_idle(lambda: self._canvas.yview_moveto(0.0))

    def _on_content_configure(self, _event: tk.Event) -> None:
        self._refresh_scrollregion()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        width = int(event.width)
        self._canvas.itemconfigure(self._window_id, width=width)

    def _refresh_scrollregion(self) -> None:
        bbox = self._canvas.bbox("all")
        if bbox is not None:
            self._canvas.configure(scrollregion=bbox)

    def _on_mousewheel(self, event: tk.Event) -> None:
        delta = getattr(event, "delta", 0)
        if not isinstance(delta, int) or delta == 0:
            return
        self._canvas.yview_scroll(int(-delta / 120), "units")

    def _on_mousewheel_linux(self, event: tk.Event) -> None:
        num = getattr(event, "num", 0)
        if num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif num == 5:
            self._canvas.yview_scroll(1, "units")
