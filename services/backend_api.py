from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import requests

from config.constants import (
    BACKEND_BASE_URL,
    BACKEND_CLIENT_WS_BASE_URL,
    BACKEND_HTTP_TIMEOUT_SEC,
)


class BackendApiError(RuntimeError):
    pass


def build_api_url(path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{BACKEND_BASE_URL}{normalized_path}"


def build_ws_url(session: str) -> str:
    separator = "&" if "?" in BACKEND_CLIENT_WS_BASE_URL else "?"
    return f"{BACKEND_CLIENT_WS_BASE_URL}{separator}session={quote(session, safe='')}"


def fetch_bootstrap(raw_session: str) -> tuple[str, list[dict[str, object]]]:
    params: dict[str, str] = {}
    if raw_session.strip():
        params["session"] = raw_session

    response = requests.get(
        build_api_url("/api/client/bootstrap"),
        params=params,
        timeout=BACKEND_HTTP_TIMEOUT_SEC,
    )
    payload = _require_mapping(
        _parse_json_payload(response),
        "bootstrap response",
    )
    if response.status_code != requests.codes.ok:
        error_message = payload.get("error")
        if isinstance(error_message, str) and error_message:
            raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")

    session = _require_string(payload.get("session"), "session")
    raw_messages = _require_list(payload.get("messages"), "messages")
    messages = [normalize_comment_item(item) for item in raw_messages]
    return session, messages


def parse_comment_event(raw_message: str) -> dict[str, object] | None:
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, Mapping):
        return None
    if payload.get("type") != "comment.created":
        return None
    try:
        return normalize_comment_item(payload.get("payload"))
    except BackendApiError:
        return None


# しおり=bookmark の単一リアクション。注目度はこの件数で測る。
BOOKMARK_REACTION_KEY = "bookmark"


def _bookmark_count_from_reactions(value: object) -> int:
    if not isinstance(value, list):
        return 0
    for reaction in value:
        if not isinstance(reaction, Mapping):
            continue
        if reaction.get("reactionKey") != BOOKMARK_REACTION_KEY:
            continue
        count = reaction.get("count")
        if isinstance(count, bool):
            continue
        if isinstance(count, int):
            return count
    return 0


def parse_reaction_update_event(raw_message: str) -> dict[str, object] | None:
    """comment.reactions.updated を解釈し、しおり件数のライブ更新に使う。"""
    try:
        payload = json.loads(raw_message)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, Mapping):
        return None
    if payload.get("type") != "comment.reactions.updated":
        return None
    body = payload.get("payload")
    if not isinstance(body, Mapping):
        return None
    comment_id = body.get("commentId")
    session = body.get("session")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int):
        return None
    if not isinstance(session, str):
        return None
    return {
        "session": session,
        "comment_id": comment_id,
        "bookmark_count": _bookmark_count_from_reactions(body.get("reactions")),
    }


def normalize_comment_item(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "comment")
    stamp = _require_nullable_string(payload.get("stamp"), "stamp")
    stamp_path = _require_nullable_string(payload.get("stampPath"), "stampPath")
    created_at = _require_string(payload.get("createdAt"), "createdAt")
    source = _require_nullable_string(payload.get("source"), "source")

    return {
        "id": _require_int(payload.get("id"), "id"),
        "session": _require_string(payload.get("session"), "session"),
        "name": _require_string(payload.get("name"), "name"),
        "real_name": _require_string(payload.get("realName"), "realName"),
        "text": _require_string(payload.get("text"), "text"),
        "time": _require_string(payload.get("time"), "time"),
        "stamp": stamp,
        "stamp_url": stamp_path,
        "source": source,
        "created_at": created_at,
        "server_time_iso": created_at,
        "bookmark_count": _bookmark_count_from_reactions(payload.get("reactions")),
    }


# === アンケート（poll）===
# 教員クライアントは未認証の /api/client/* 経由でアンケートを登録・配信・集計する。


def fetch_polls(session: str) -> list[dict[str, object]]:
    params: dict[str, str] = {}
    if session.strip():
        params["session"] = session
    response = requests.get(
        build_api_url("/api/client/polls"),
        params=params,
        timeout=BACKEND_HTTP_TIMEOUT_SEC,
    )
    payload = _parse_json_payload(response)
    if response.status_code != requests.codes.ok:
        if isinstance(payload, Mapping):
            error_message = payload.get("error")
            if isinstance(error_message, str) and error_message:
                raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")
    raw_items = _require_list(payload, "polls")
    return [normalize_poll_item(item) for item in raw_items]


def create_poll(
    session: str, question: str, options: Sequence[str], duration_sec: int
) -> dict[str, object]:
    url = build_api_url("/api/client/polls")
    try:
        response = requests.post(
            url,
            json={
                "session": session,
                "question": question,
                "options": list(options),
                "durationSec": duration_sec,
            },
            timeout=BACKEND_HTTP_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise BackendApiError(f"POST {url} failed: {exc}") from exc
    payload = _require_mapping(_parse_json_payload(response), "poll response")
    if response.status_code != requests.codes.created:
        error_message = payload.get("error")
        if isinstance(error_message, str) and error_message:
            raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")
    return normalize_poll_item(payload)


def start_poll(session: str, poll_id: int) -> dict[str, object]:
    url = build_api_url("/api/client/polls/start")
    try:
        response = requests.post(
            url,
            json={"session": session, "pollId": poll_id},
            timeout=BACKEND_HTTP_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise BackendApiError(f"POST {url} failed: {exc}") from exc
    payload = _require_mapping(_parse_json_payload(response), "poll start response")
    if response.status_code != requests.codes.ok:
        error_message = payload.get("error")
        if isinstance(error_message, str) and error_message:
            raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")
    return normalize_poll_started(payload)


def fetch_poll_results(
    poll_id: int, run_id: int | None = None, session: str | None = None
) -> dict[str, object]:
    params: dict[str, str] = {"pollId": str(poll_id)}
    if run_id is not None:
        params["runId"] = str(run_id)
    if session and session.strip():
        params["session"] = session
    response = requests.get(
        build_api_url("/api/client/poll-results"),
        params=params,
        timeout=BACKEND_HTTP_TIMEOUT_SEC,
    )
    payload = _require_mapping(_parse_json_payload(response), "poll results")
    if response.status_code != requests.codes.ok:
        error_message = payload.get("error")
        if isinstance(error_message, str) and error_message:
            raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")
    return normalize_poll_results(payload)


def normalize_poll_item(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "poll")
    return {
        "id": _require_int(payload.get("id"), "id"),
        "session": _require_string(payload.get("session"), "session"),
        "question": _require_string(payload.get("question"), "question"),
        "options": _require_string_list(payload.get("options"), "options"),
        "duration_sec": _require_int(payload.get("durationSec"), "durationSec"),
        "created_at": _require_string(payload.get("createdAt"), "createdAt"),
    }


def normalize_poll_started(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "poll started")
    return {
        "poll_id": _require_int(payload.get("pollId"), "pollId"),
        "run_id": _require_int(payload.get("runId"), "runId"),
        "session": _require_string(payload.get("session"), "session"),
        "question": _require_string(payload.get("question"), "question"),
        "options": _require_string_list(payload.get("options"), "options"),
        "duration_sec": _require_int(payload.get("durationSec"), "durationSec"),
        "started_at": _require_string(payload.get("startedAt"), "startedAt"),
    }


def normalize_poll_answer(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "poll answer")
    return {
        "name": _require_string(payload.get("name"), "name"),
        "real_name": _require_string(payload.get("realName"), "realName"),
        "option_index": _require_int(payload.get("optionIndex"), "optionIndex"),
        "response_ms": _require_int(payload.get("responseMs"), "responseMs"),
        "client_elapsed_ms": _require_nullable_int(
            payload.get("clientElapsedMs"), "clientElapsedMs"
        ),
        "created_at": _require_string(payload.get("createdAt"), "createdAt"),
    }


def normalize_poll_results(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "poll results")
    raw_counts = _require_list(payload.get("optionCounts"), "optionCounts")
    option_counts = [_require_int(item, "optionCount") for item in raw_counts]
    raw_answers = _require_list(payload.get("answers"), "answers")
    answers = [normalize_poll_answer(item) for item in raw_answers]
    return {
        "poll_id": _require_int(payload.get("pollId"), "pollId"),
        "run_id": _require_int(payload.get("runId"), "runId"),
        "question": _require_string(payload.get("question"), "question"),
        "options": _require_string_list(payload.get("options"), "options"),
        "duration_sec": _require_int(payload.get("durationSec"), "durationSec"),
        "started_at": _require_string(payload.get("startedAt"), "startedAt"),
        "delivered_count": _require_int(
            payload.get("deliveredCount"), "deliveredCount"
        ),
        "answer_count": _require_int(payload.get("answerCount"), "answerCount"),
        "answer_rate": _require_number(payload.get("answerRate"), "answerRate"),
        "average_response_ms": _require_nullable_number(
            payload.get("averageResponseMs"), "averageResponseMs"
        ),
        "option_counts": option_counts,
        "answers": answers,
    }


def _parse_json_payload(response: requests.Response) -> object:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BackendApiError(f"{response.status_code} {response.reason}") from exc

    return payload


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise BackendApiError(f"{field_name} is invalid")
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise BackendApiError(f"{field_name} is invalid")
    return list(value)


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise BackendApiError(f"{field_name} is invalid")
    return value


def _require_nullable_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BackendApiError(f"{field_name} is invalid")
    return value


def _require_nullable_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _require_int(value, field_name)


def _require_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BackendApiError(f"{field_name} is invalid")
    return float(value)


def _require_nullable_number(value: object, field_name: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, field_name)


def _require_string_list(value: object, field_name: str) -> list[str]:
    items = _require_list(value, field_name)
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise BackendApiError(f"{field_name} is invalid")
        result.append(item)
    return result
