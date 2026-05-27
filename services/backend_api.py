from __future__ import annotations

import base64
import hashlib
import json
import socket
import ssl
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import requests
from wsproto import WSConnection
from wsproto.connection import ConnectionType
from wsproto.events import (
    AcceptConnection,
    CloseConnection,
    Ping,
    RejectConnection,
    RejectData,
    Request,
    TextMessage,
)

from config.constants import (
    BACKEND_BASE_URL,
    BACKEND_CLIENT_WS_BASE_URL,
    BACKEND_HTTP_TIMEOUT_SEC,
    BACKEND_TRANSCRIPTION_WS_BASE_URL,
    BACKEND_UPLOAD_TIMEOUT_SEC,
    BACKEND_WS_ORIGIN,
    TRANSCRIPTION_WS_PART_SIZE_BYTES,
)


class BackendApiError(RuntimeError):
    pass


def build_api_url(path: str) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    return f"{BACKEND_BASE_URL}{normalized_path}"


def build_ws_url(session: str) -> str:
    separator = "&" if "?" in BACKEND_CLIENT_WS_BASE_URL else "?"
    return f"{BACKEND_CLIENT_WS_BASE_URL}{separator}session={quote(session, safe='')}"


def build_transcription_ws_url(session: str) -> str:
    separator = "&" if "?" in BACKEND_TRANSCRIPTION_WS_BASE_URL else "?"
    return f"{BACKEND_TRANSCRIPTION_WS_BASE_URL}{separator}session={quote(session, safe='')}"


def upload_transcription_chunk_ws(
    session: str,
    chunk_sequence: int,
    recorded_from: str,
    recorded_to: str,
    audio_bytes: bytes,
) -> dict[str, object]:
    if not audio_bytes:
        raise BackendApiError("audio chunk is empty")

    parts = [
        audio_bytes[index : index + TRANSCRIPTION_WS_PART_SIZE_BYTES]
        for index in range(0, len(audio_bytes), TRANSCRIPTION_WS_PART_SIZE_BYTES)
    ]
    if not parts:
        raise BackendApiError("audio chunk is empty")

    socket_handle, connection = _open_transcription_websocket(
        build_transcription_ws_url(session)
    )
    try:
        socket_handle.settimeout(BACKEND_UPLOAD_TIMEOUT_SEC)
        start_message = {
            "type": "transcription.chunk.start",
            "payload": {
                "chunkSequence": chunk_sequence,
                "recordedFrom": recorded_from,
                "recordedTo": recorded_to,
                "totalParts": len(parts),
                "totalBytes": len(audio_bytes),
                "audioSha256": _sha256_hex(audio_bytes),
            },
        }
        _send_transcription_ws_json(socket_handle, connection, start_message)
        start_payload = _extract_transcription_ws_payload(
            _receive_transcription_ws_json(socket_handle, connection),
            "transcription.chunk.start.ack",
        )
        if _require_int(start_payload.get("chunkSequence"), "chunkSequence") != chunk_sequence:
            raise BackendApiError("transcription websocket start ack is invalid")

        for part_sequence, part in enumerate(parts):
            part_message = {
                "type": "transcription.chunk.part",
                "payload": {
                    "chunkSequence": chunk_sequence,
                    "partSequence": part_sequence,
                    "audioBase64": base64.b64encode(part).decode("ascii"),
                    "audioSha256": _sha256_hex(part),
                },
            }
            _send_transcription_ws_json(socket_handle, connection, part_message)
            part_payload = _extract_transcription_ws_payload(
                _receive_transcription_ws_json(socket_handle, connection),
                "transcription.chunk.part.ack",
            )
            if _require_int(part_payload.get("chunkSequence"), "chunkSequence") != chunk_sequence:
                raise BackendApiError("transcription websocket part ack is invalid")
            if _require_int(part_payload.get("partSequence"), "partSequence") != part_sequence:
                raise BackendApiError("transcription websocket part ack is invalid")

        finish_message = {
            "type": "transcription.chunk.finish",
            "payload": {
                "chunkSequence": chunk_sequence,
            },
        }
        _send_transcription_ws_json(socket_handle, connection, finish_message)
        completed_payload = _extract_transcription_ws_payload(
            _receive_transcription_ws_json(socket_handle, connection),
            "transcription.chunk.completed",
        )
        if (
            _require_int(completed_payload.get("chunkSequence"), "chunkSequence")
            != chunk_sequence
        ):
            raise BackendApiError("transcription websocket completion is invalid")
        return normalize_transcription_item(
            completed_payload.get("transcription")
        )
    finally:
        _close_transcription_websocket(socket_handle, connection)


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
        audio_file = open(audio_path, "rb")
    except OSError as exc:
        raise BackendApiError(f"Failed to open audio chunk: {exc}") from exc

    with audio_file:
        try:
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


def _sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _open_transcription_websocket(url: str) -> tuple[socket.socket, WSConnection]:
    parsed = requests.utils.urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        raise BackendApiError("websocket host is invalid")

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "wss" else 80

    try:
        raw_socket = socket.create_connection(
            (hostname, port),
            timeout=BACKEND_HTTP_TIMEOUT_SEC,
        )
    except OSError as exc:
        raise BackendApiError(f"Failed to connect websocket: {exc}") from exc

    raw_socket.settimeout(BACKEND_HTTP_TIMEOUT_SEC)
    if parsed.scheme == "wss":
        context = ssl.create_default_context()
        socket_handle = context.wrap_socket(raw_socket, server_hostname=hostname)
        socket_handle.settimeout(BACKEND_HTTP_TIMEOUT_SEC)
    else:
        socket_handle = raw_socket

    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"

    connection = WSConnection(ConnectionType.CLIENT)
    handshake = connection.send(
        Request(
            host=parsed.netloc,
            target=target,
            extra_headers=[(b"origin", BACKEND_WS_ORIGIN.encode("utf-8"))],
        )
    )
    try:
        socket_handle.sendall(handshake)
    except OSError as exc:
        try:
            socket_handle.close()
        except OSError:
            pass
        raise BackendApiError(f"Failed to send websocket handshake: {exc}") from exc

    try:
        _complete_transcription_websocket_handshake(socket_handle, connection)
    except Exception:
        try:
            socket_handle.close()
        except OSError:
            pass
        raise

    return socket_handle, connection


def _complete_transcription_websocket_handshake(
    socket_handle: socket.socket,
    connection: WSConnection,
) -> None:
    while True:
        for event in _receive_transcription_ws_events(socket_handle, connection):
            if isinstance(event, AcceptConnection):
                return
            if isinstance(event, RejectConnection):
                raise BackendApiError(
                    f"websocket rejected with status {event.status_code}"
                )
            if isinstance(event, RejectData):
                continue
            if isinstance(event, Ping):
                _send_transcription_ws_event(socket_handle, connection, event.response())
                continue
            if isinstance(event, CloseConnection):
                try:
                    _send_transcription_ws_event(
                        socket_handle, connection, event.response()
                    )
                except BackendApiError:
                    pass
                raise BackendApiError("websocket closed during handshake")


def _send_transcription_ws_json(
    socket_handle: socket.socket,
    connection: WSConnection,
    payload: Mapping[str, object],
) -> None:
    text = json.dumps(payload, separators=(",", ":"))
    _send_transcription_ws_event(socket_handle, connection, TextMessage(data=text))


def _send_transcription_ws_event(
    socket_handle: socket.socket,
    connection: WSConnection,
    event: object,
) -> None:
    try:
        socket_handle.sendall(connection.send(event))
    except OSError as exc:
        raise BackendApiError(f"WebSocket send failed: {exc}") from exc


def _receive_transcription_ws_json(
    socket_handle: socket.socket,
    connection: WSConnection,
) -> Mapping[str, object]:
    message_parts: list[str] = []
    while True:
        for event in _receive_transcription_ws_events(socket_handle, connection):
            if isinstance(event, TextMessage):
                message_parts.append(event.data)
                if not event.message_finished:
                    continue
                try:
                    payload = json.loads("".join(message_parts))
                except json.JSONDecodeError as exc:
                    raise BackendApiError("transcription websocket response is invalid") from exc
                return _require_mapping(payload, "transcription websocket response")
            if isinstance(event, Ping):
                _send_transcription_ws_event(socket_handle, connection, event.response())
                continue
            if isinstance(event, RejectConnection):
                raise BackendApiError(
                    f"websocket rejected with status {event.status_code}"
                )
            if isinstance(event, RejectData):
                continue
            if isinstance(event, CloseConnection):
                try:
                    _send_transcription_ws_event(
                        socket_handle, connection, event.response()
                    )
                except BackendApiError:
                    pass
                raise BackendApiError("transcription websocket closed unexpectedly")
            if isinstance(event, AcceptConnection):
                continue


def _receive_transcription_ws_events(
    socket_handle: socket.socket,
    connection: WSConnection,
):
    try:
        received = socket_handle.recv(4096)
    except socket.timeout as exc:
        raise BackendApiError("transcription websocket timed out") from exc
    except OSError as exc:
        raise BackendApiError(f"WebSocket receive failed: {exc}") from exc

    if not received:
        connection.receive_data(None)
    else:
        connection.receive_data(received)
    return connection.events()


def _extract_transcription_ws_payload(
    message: Mapping[str, object],
    expected_type: str,
) -> Mapping[str, object]:
    message_type = _require_string(message.get("type"), "type")
    payload = _require_mapping(message.get("payload"), "payload")
    if message_type == "transcription.chunk.error":
        raise BackendApiError(_require_string(payload.get("message"), "message"))
    if message_type != expected_type:
        raise BackendApiError(
            f"Unexpected transcription websocket response: {message_type}"
        )
    return payload


def _close_transcription_websocket(
    socket_handle: socket.socket,
    connection: WSConnection,
) -> None:
    try:
        close_bytes = connection.send(CloseConnection(code=1000, reason=""))
        if close_bytes:
            socket_handle.sendall(close_bytes)
    except Exception:
        pass
    try:
        socket_handle.close()
    except OSError:
        pass


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
