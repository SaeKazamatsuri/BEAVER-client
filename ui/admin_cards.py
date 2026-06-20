from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    bookmarks: int = 0


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


def _bookmark_count(message: dict[str, object]) -> int:
    value = message.get("bookmark_count")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def build_comment_history_rows(
    messages: Sequence[dict[str, object]],
    *,
    order: str = "chronological",
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
                bookmarks=_bookmark_count(message),
            )
        )
    if order == "bookmark":
        # 安定ソートなので同数は元の順序（message_log 順）を維持する。
        rows.sort(key=lambda row: row.bookmarks, reverse=True)
    return rows


def build_comment_history_signature(
    messages: Sequence[dict[str, object]],
) -> tuple[tuple[str, str, str, str, int], ...]:
    return tuple(
        (
            string_value(message.get("time")),
            string_value(message.get("name")),
            string_value(message.get("text")),
            string_value(message.get("created_at")),
            _bookmark_count(message),
        )
        for message in messages
        if not _is_stamp_message(message)
    )


# === アンケート集計表示 ===


@dataclass(frozen=True, slots=True)
class PollOptionResult:
    index: int
    label: str
    count: int
    percentage: float  # 回答に占める割合 (0-100)


@dataclass(frozen=True, slots=True)
class PollAnswerResult:
    name: str
    option_label: str
    response_sec: float


@dataclass(frozen=True, slots=True)
class PollResultsView:
    question: str
    options: list[PollOptionResult]
    delivered_count: int
    answer_count: int
    answer_rate_percent: float
    average_response_sec: float | None
    answers: list[PollAnswerResult]


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return value


def _float_value(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, str)]


def build_poll_results_view(results: Mapping[str, object]) -> PollResultsView:
    """正規化済みのアンケート集計を、描画しやすい純粋なビューに変換する。"""
    options = _string_list(results.get("options"))
    raw_counts = results.get("option_counts")
    counts = (
        [c for c in raw_counts if isinstance(c, int) and not isinstance(c, bool)]
        if isinstance(raw_counts, Sequence)
        and not isinstance(raw_counts, (str, bytes, bytearray))
        else []
    )
    answer_count = _int_value(results.get("answer_count"))
    delivered_count = _int_value(results.get("delivered_count"))
    answer_rate = _float_value(results.get("answer_rate")) or 0.0
    average_response_ms = _float_value(results.get("average_response_ms"))

    option_results: list[PollOptionResult] = []
    for index, label in enumerate(options):
        count = counts[index] if index < len(counts) else 0
        percentage = (count / answer_count * 100.0) if answer_count > 0 else 0.0
        option_results.append(
            PollOptionResult(
                index=index, label=label, count=count, percentage=percentage
            )
        )

    answers: list[PollAnswerResult] = []
    raw_answers = results.get("answers")
    if isinstance(raw_answers, Sequence) and not isinstance(
        raw_answers, (str, bytes, bytearray)
    ):
        for answer in raw_answers:
            if not isinstance(answer, Mapping):
                continue
            option_index = _int_value(answer.get("option_index"), -1)
            option_label = (
                options[option_index]
                if 0 <= option_index < len(options)
                else "-"
            )
            response_ms = _int_value(answer.get("response_ms"))
            answers.append(
                PollAnswerResult(
                    name=string_value(answer.get("name")) or "名前なし",
                    option_label=option_label,
                    response_sec=response_ms / 1000.0,
                )
            )

    return PollResultsView(
        question=string_value(results.get("question")) or "-",
        options=option_results,
        delivered_count=delivered_count,
        answer_count=answer_count,
        answer_rate_percent=answer_rate * 100.0,
        average_response_sec=(
            average_response_ms / 1000.0 if average_response_ms is not None else None
        ),
        answers=answers,
    )

