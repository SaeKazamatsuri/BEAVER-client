from __future__ import annotations

import re
import tkinter as tk
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import time

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

NAME_FONT = ("Yu Gothic UI", -16, "bold")
TIME_FONT = ("Yu Gothic UI", -16)
BODY_FONT = ("Yu Gothic UI", -28, "bold")


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
    source: str | None = None


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
    source = _required_string(message.get("source")) if "source" in message else None

    return CommentEntry(
        id=entry_id,
        session=session,
        name=name,
        text=text,
        time=time,
        stamp_url=None,
        created_at=created_at,
        from_history=from_history,
        source=source,
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


def _bbox_or_default(
    canvas: tk.Canvas,
    item_id: int,
    default: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    bbox = canvas.bbox(item_id)
    if bbox is None:
        return default
    return bbox


def _create_rounded_rectangle(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    radius: int,
    tags: tuple[str, ...],
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
        canvas.create_polygon(
            points,
            smooth=True,
            splinesteps=24,
            tags=tags,
            **kwargs,
        )
    )


def _measure_text_bbox(
    canvas: tk.Canvas,
    *,
    x: int,
    y: int,
    anchor: str,
    fill: str,
    font: tuple[object, ...],
    text: str,
    fallback: tuple[int, int, int, int],
    width: int | None = None,
) -> tuple[int, int, int, int]:
    kwargs: dict[str, object] = {
        "anchor": anchor,
        "fill": fill,
        "font": font,
        "text": text,
    }
    if width is not None:
        kwargs["justify"] = "left"
        kwargs["width"] = width
    item_id = canvas.create_text(x, y, **kwargs)
    bbox = _bbox_or_default(canvas, item_id, fallback)
    canvas.delete(item_id)
    return bbox


def _measure_body_bbox(
    canvas: tk.Canvas,
    *,
    body_x: int,
    body_y: int,
    body_width: int,
    body_text: str,
) -> tuple[int, int, int, int]:
    return _measure_text_bbox(
        canvas,
        x=body_x,
        y=body_y,
        anchor="nw",
        fill=BODY_TEXT_FG,
        font=BODY_FONT,
        text=body_text,
        width=body_width,
        fallback=(body_x, body_y, body_x + body_width, body_y + 40),
    )


def _card_total_height(
    *,
    card_top: int,
    card_bottom: int,
    shadow_offset_y: int,
    bottom_padding: int,
) -> int:
    return (card_bottom - card_top) + shadow_offset_y + bottom_padding


def _draw_comment_card(
    canvas: tk.Canvas,
    entry: CommentEntry,
    *,
    card_left: int,
    card_top: int,
    card_right: int,
    tags: tuple[str, ...],
    bg_color: str = CARD_BG,
) -> int:
    shadow_offset_x = 6
    shadow_offset_y = 6
    card_inner_left = card_left + 18
    card_inner_right = card_right - 18
    header_y = card_top + 12
    label_x = card_inner_left
    body_width = max(120, card_inner_right - card_inner_left)
    body_text = insert_soft_wraps(entry.text)

    time_bbox = _measure_text_bbox(
        canvas,
        x=card_inner_right,
        y=header_y,
        anchor="ne",
        fill=TIME_TEXT_FG,
        font=TIME_FONT,
        text=entry.time,
        fallback=(card_inner_right - 80, header_y, card_inner_right, header_y + 24),
    )
    label_width = max(80, time_bbox[0] - label_x - 16)
    label_bbox = _measure_text_bbox(
        canvas,
        x=label_x,
        y=header_y,
        anchor="nw",
        fill=NAME_TAG_FG,
        font=NAME_FONT,
        text=entry.name,
        width=label_width,
        fallback=(label_x, header_y, label_x + label_width, header_y + 24),
    )
    label_tag_bottom = label_bbox[3] + 4
    body_y = max(label_tag_bottom, time_bbox[3]) + 10
    body_bbox = _measure_body_bbox(
        canvas,
        body_x=card_inner_left,
        body_y=body_y,
        body_width=body_width,
        body_text=body_text,
    )

    card_bottom = max(card_top + 94, body_bbox[3] + 12)
    height = _card_total_height(
        card_top=card_top,
        card_bottom=card_bottom,
        shadow_offset_y=shadow_offset_y,
        bottom_padding=6,
    )

    shadow_id = _create_rounded_rectangle(
        canvas,
        card_left + shadow_offset_x,
        card_top + shadow_offset_y,
        card_right + shadow_offset_x,
        card_bottom + shadow_offset_y,
        radius=28,
        fill=CARD_SHADOW,
        outline="",
        tags=tags,
    )
    _create_rounded_rectangle(
        canvas,
        card_left,
        card_top,
        card_right,
        card_bottom,
        radius=28,
        fill=bg_color,
        outline=CARD_BORDER,
        width=3,
        tags=tags,
    )
    _create_rounded_rectangle(
        canvas,
        label_bbox[0] - 10,
        label_bbox[1] - 4,
        label_bbox[2] + 10,
        label_bbox[3] + 4,
        radius=18,
        fill=NAME_TAG_BG,
        outline=CARD_BORDER,
        width=2,
        tags=tags,
    )

    canvas.create_text(
        label_x,
        header_y,
        anchor="nw",
        fill=NAME_TAG_FG,
        font=NAME_FONT,
        text=entry.name,
        width=label_width,
        tags=tags,
    )
    canvas.create_text(
        card_inner_right,
        header_y,
        anchor="ne",
        fill=TIME_TEXT_FG,
        font=TIME_FONT,
        text=entry.time,
        tags=tags,
    )
    canvas.create_text(
        card_inner_left,
        body_y,
        anchor="nw",
        fill=BODY_TEXT_FG,
        font=BODY_FONT,
        justify="left",
        text=body_text,
        width=body_width,
        tags=tags,
    )

    canvas.tag_lower(shadow_id)
    return height


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
        card_left = 4
        card_top = 4
        card_right = max(card_left + 220, width - card_left - 6)
        height = _draw_comment_card(
            self,
            self._entry,
            card_left=card_left,
            card_top=card_top,
            card_right=card_right,
            tags=(),
        )
        if height != self._last_height:
            self._last_height = height
            self.configure(height=height)


class CommentListView(tk.Frame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, background=COMMENT_COLUMN_BG)
        self._comments: list[CommentEntry] = []
        self._redraw_scheduled = False

        self._ai_question_entry: CommentEntry | None = None
        self._ai_question_count: int = 0
        self._ai_question_expiration: float = 0.0
        self._ai_question_timer: str | None = None

        self._canvas = tk.Canvas(
            self,
            background=COMMENT_COLUMN_BG,
            borderwidth=0,
            highlightthickness=0,
            relief="flat",
        )
        self._canvas.pack(fill="both", expand=True)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._canvas.bind("<MouseWheel>", self._on_mousewheel)
        self._canvas.bind("<Button-4>", self._on_mousewheel_linux)
        self._canvas.bind("<Button-5>", self._on_mousewheel_linux)
        self.after_idle(self._redraw)

    @property
    def overlay_canvas(self) -> tk.Canvas:
        return self._canvas

    def clear(self) -> None:
        self._comments.clear()
        self._ai_question_entry = None
        self._ai_question_count = 0
        if self._ai_question_timer:
            self.after_cancel(self._ai_question_timer)
            self._ai_question_timer = None
        self._canvas.delete("comment_card")
        self.after_idle(self._refresh_scrollregion)

    def set_comments(self, comments: Sequence[CommentEntry]) -> None:
        filtered = []
        for c in reversed(list(comments)):
            if c.source == "ai_question":
                continue
            filtered.append(c)
        self._comments = filtered
        self._schedule_redraw()

    def add_comment(self, comment: CommentEntry) -> None:
        if comment.source == "ai_question" and not comment.from_history:
            now = time.time()
            if self._ai_question_entry is not None and now < self._ai_question_expiration:
                self._ai_question_count += 1
            else:
                self._ai_question_count = 1
            
            self._ai_question_entry = comment
            self._ai_question_expiration = now + 300.0  # 5分間
            
            if self._ai_question_timer:
                self.after_cancel(self._ai_question_timer)
            self._ai_question_timer = self.after(300000, self._expire_ai_question)
            
            self._schedule_redraw()
            return

        self._comments.insert(0, comment)
        self._schedule_redraw()
        self.after_idle(lambda: self._canvas.yview_moveto(0.0))

    def _expire_ai_question(self) -> None:
        self._ai_question_entry = None
        self._ai_question_timer = None
        self._schedule_redraw()

    def _get_ai_question_bg(self, count: int) -> str:
        ratio = min((count - 1) / 10.0, 1.0)
        g = int(255 - (255 - 128) * ratio)
        b = int(255 - (255 - 223) * ratio)
        return f"#ff{g:02x}{b:02x}"

    def _schedule_redraw(self) -> None:
        if self._redraw_scheduled:
            return
        self._redraw_scheduled = True
        self.after_idle(self._redraw)

    def _on_canvas_configure(self, event: tk.Event) -> None:
        if int(event.width) <= 1:
            return
        self._schedule_redraw()

    def _redraw(self) -> None:
        self._redraw_scheduled = False
        width = self._canvas.winfo_width()
        if width <= 1:
            self.after(10, self._schedule_redraw)
            return

        self._canvas.delete("comment_card")

        card_left = 12
        current_y = 10
        card_right = max(card_left + 220, width - 18)

        if self._ai_question_entry is not None:
            bg_color = self._get_ai_question_bg(self._ai_question_count)
            height = _draw_comment_card(
                self._canvas,
                self._ai_question_entry,
                card_left=card_left,
                card_top=current_y,
                card_right=card_right,
                tags=("comment_card",),
                bg_color=bg_color,
            )
            current_y += height + 15
            self._canvas.create_line(
                card_left - 4, current_y - 8, card_right + 4, current_y - 8,
                fill="#5aaecb",
                width=2,
                tags=("comment_card",)
            )

        for entry in self._comments:
            height = _draw_comment_card(
                self._canvas,
                entry,
                card_left=card_left,
                card_top=current_y,
                card_right=card_right,
                tags=("comment_card",),
            )
            current_y += height + 5

        self._refresh_scrollregion()
        if self._canvas.find_withtag("overlay_balloon"):
            self._canvas.tag_raise("overlay_balloon")
            self._canvas.tag_lower("comment_card", "overlay_balloon")
        else:
            self._canvas.tag_lower("comment_card")

    def _refresh_scrollregion(self) -> None:
        bbox = self._canvas.bbox("comment_card")
        width = max(1, self._canvas.winfo_width())
        height = max(1, self._canvas.winfo_height())
        if bbox is None:
            self._canvas.configure(scrollregion=(0, 0, width, height))
            return
        self._canvas.configure(
            scrollregion=(
                0,
                0,
                max(width, bbox[2] + 12),
                max(height, bbox[3] + 16),
            )
        )

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
