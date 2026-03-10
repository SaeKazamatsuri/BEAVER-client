from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AdminListCard:
    kind: str
    tag_text: str
    title: str
    body: str
    timestamp: str


@dataclass(frozen=True, slots=True)
class CommentHistoryRow:
    timestamp: str
    name: str
    text: str


def string_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return ""


def format_timestamp(value: object) -> str:
    raw_value = string_value(value)
    if not raw_value:
        return "-"
    normalized = raw_value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return raw_value
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _is_stamp_message(message: dict[str, object]) -> bool:
    return bool(
        string_value(message.get("stamp_url")) or string_value(message.get("stamp"))
    )


def build_comment_history_rows(
    messages: Sequence[dict[str, object]],
) -> list[CommentHistoryRow]:
    rows: list[CommentHistoryRow] = []
    for message in messages:
        if _is_stamp_message(message):
            continue

        timestamp = string_value(message.get("time")) or format_timestamp(
            message.get("created_at")
        )
        rows.append(
            CommentHistoryRow(
                timestamp=timestamp,
                name=string_value(message.get("name")) or "名前なし",
                text=string_value(message.get("text")) or "-",
            )
        )
    return rows


def build_comment_history_signature(
    messages: Sequence[dict[str, object]],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            string_value(message.get("time")),
            string_value(message.get("name")),
            string_value(message.get("text")),
            string_value(message.get("created_at")),
        )
        for message in messages
        if not _is_stamp_message(message)
    )


def build_transcription_timeline(
    items: Sequence[dict[str, object]],
    events: Sequence[dict[str, object]],
) -> list[AdminListCard]:
    timeline: list[tuple[str, int, AdminListCard]] = []

    for item in items:
        item_id = item.get("id")
        sort_order = item_id if isinstance(item_id, int) else 0
        timeline.append(
            (
                string_value(item.get("created_at")),
                sort_order,
                AdminListCard(
                    kind="transcription",
                    tag_text="TEXT",
                    title="文字起こし",
                    body=string_value(item.get("text")) or "-",
                    timestamp=format_timestamp(item.get("created_at")),
                ),
            )
        )

    event_count = len(events)
    for index, event in enumerate(events):
        timeline.append(
            (
                string_value(event.get("created_at")),
                event_count - index,
                AdminListCard(
                    kind="status",
                    tag_text="STATUS",
                    title=string_value(event.get("event")) or "状態更新",
                    body=string_value(event.get("detail")) or "-",
                    timestamp=format_timestamp(event.get("created_at")),
                ),
            )
        )

    timeline.sort(
        key=lambda entry: (
            entry[0],
            1 if entry[2].kind == "transcription" else 0,
            entry[1],
        ),
        reverse=True,
    )
    return [entry[2] for entry in timeline]
