from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import requests

from config.constants import (
    BACKEND_BASE_URL,
    BACKEND_HTTP_TIMEOUT_SEC,
    BACKEND_UPLOAD_TIMEOUT_SEC,
    BACKEND_WS_BASE_URL,
)


class BackendApiError(RuntimeError):
    pass


def build_api_url(path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{BACKEND_BASE_URL}{normalized_path}"


def build_ws_url(session: str) -> str:
    separator = "&" if "?" in BACKEND_WS_BASE_URL else "?"
    return f"{BACKEND_WS_BASE_URL}{separator}session={quote(session, safe='')}"


def fetch_bootstrap(raw_session: str) -> tuple[str, list[dict[str, object]]]:
    params: dict[str, str] = {}
    if raw_session.strip():
        params["session"] = raw_session

    response = requests.get(
        build_api_url("/api/bootstrap"),
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


def fetch_transcriptions(raw_session: str) -> list[dict[str, object]]:
    params: dict[str, str] = {}
    if raw_session.strip():
        params["session"] = raw_session

    response = requests.get(
        build_api_url("/api/transcriptions"),
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

    raw_items = _require_list(payload, "transcriptions")
    return [normalize_transcription_item(item) for item in raw_items]


def post_transcription(session: str, text: str) -> dict[str, object]:
    url = build_api_url("/api/transcriptions")
    try:
        response = requests.post(
            url,
            json={"session": session, "text": text},
            timeout=BACKEND_HTTP_TIMEOUT_SEC,
        )
    except requests.RequestException as exc:
        raise BackendApiError(f"POST {url} failed: {exc}") from exc
    payload = _require_mapping(
        _parse_json_payload(response),
        "transcription response",
    )
    if response.status_code != requests.codes.created:
        error_message = payload.get("error")
        if isinstance(error_message, str) and error_message:
            raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")
    return normalize_transcription_item(payload)


def post_transcription_chunk(
    session: str,
    chunk_sequence: int,
    recorded_from: str,
    recorded_to: str,
    audio_path: str,
) -> dict[str, object]:
    url = build_api_url("/api/transcription-chunks")
    try:
        with open(audio_path, "rb") as audio_file:
            response = requests.post(
                url,
                data={
                    "session": session,
                    "chunkSequence": str(chunk_sequence),
                    "recordedFrom": recorded_from,
                    "recordedTo": recorded_to,
                },
                files={
                    "audio": ("chunk.wav", audio_file, "audio/wav"),
                },
                timeout=BACKEND_UPLOAD_TIMEOUT_SEC,
            )
    except OSError as exc:
        raise BackendApiError(f"Failed to open audio chunk: {exc}") from exc
    except requests.RequestException as exc:
        raise BackendApiError(f"POST {url} failed: {exc}") from exc

    payload = _require_mapping(
        _parse_json_payload(response),
        "transcription chunk response",
    )
    if response.status_code not in (requests.codes.ok, requests.codes.created):
        error_message = payload.get("error")
        if isinstance(error_message, str) and error_message:
            raise BackendApiError(error_message)
        raise BackendApiError(f"{response.status_code} {response.reason}")
    return normalize_transcription_item(payload)


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


def normalize_comment_item(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "comment")
    stamp = _require_nullable_string(payload.get("stamp"), "stamp")
    stamp_path = _require_nullable_string(payload.get("stampPath"), "stampPath")
    created_at = _require_string(payload.get("createdAt"), "createdAt")

    return {
        "id": _require_int(payload.get("id"), "id"),
        "session": _require_string(payload.get("session"), "session"),
        "name": _require_string(payload.get("name"), "name"),
        "real_name": _require_string(payload.get("realName"), "realName"),
        "text": _require_string(payload.get("text"), "text"),
        "time": _require_string(payload.get("time"), "time"),
        "stamp": stamp,
        "stamp_url": stamp_path,
        "created_at": created_at,
        "server_time_iso": created_at,
    }


def normalize_transcription_item(value: object) -> dict[str, object]:
    payload = _require_mapping(value, "transcription")
    created_at = _require_string(payload.get("createdAt"), "createdAt")
    return {
        "id": _require_int(payload.get("id"), "id"),
        "session": _require_string(payload.get("session"), "session"),
        "text": _require_string(payload.get("text"), "text"),
        "created_at": created_at,
        "server_time_iso": created_at,
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
