from __future__ import annotations

import queue
import socket
import ssl
import threading
from urllib.parse import urlsplit
from tkinter import messagebox

import app_state as state
from backend_api import (
    BackendApiError,
    build_ws_url,
    fetch_bootstrap,
    fetch_transcriptions,
    parse_comment_event,
)
from constants import BACKEND_HTTP_TIMEOUT_SEC, BACKEND_WS_ORIGIN
from overlay import should_drop_on_arrival
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

_connection_lock = threading.Lock()
_connection_serial = 0
_active_socket: socket.socket | None = None
_active_stop_event: threading.Event | None = None


def _on_history(data):
    if isinstance(data, list):
        filtered: list[dict] = []
        queued_entries: list[dict] = []
        for message in data:
            if should_drop_on_arrival(message):
                continue
            filtered.append(message)
            entry = dict(message)
            entry["_from_history"] = True
            queued_entries.append(entry)
        state.message_log.clear()
        state.message_log.extend(filtered)
        while True:
            try:
                state.message_queue.get_nowait()
            except queue.Empty:
                break
        for entry in queued_entries:
            state.message_queue.put(entry)


def _on_new_comment(entry):
    if isinstance(entry, dict):
        if should_drop_on_arrival(entry):
            return
        state.message_log.append(entry)
        state.message_queue.put(entry)


def _next_connection_serial() -> int:
    global _connection_serial
    with _connection_lock:
        _connection_serial += 1
        return _connection_serial


def _is_current_serial(serial: int) -> bool:
    with _connection_lock:
        return serial == _connection_serial


def _clear_message_queue() -> None:
    while True:
        try:
            state.message_queue.get_nowait()
        except queue.Empty:
            return


def _set_active_socket(
    serial: int, stop_event: threading.Event, sock: socket.socket
) -> None:
    global _active_socket, _active_stop_event
    with _connection_lock:
        if serial != _connection_serial:
            return
        _active_socket = sock
        _active_stop_event = stop_event


def _clear_active_socket(serial: int, sock: socket.socket) -> None:
    global _active_socket, _active_stop_event
    with _connection_lock:
        if serial != _connection_serial:
            return
        if _active_socket is sock:
            _active_socket = None
            _active_stop_event = None


def disconnect_session(show_status: bool = True) -> None:
    global _active_socket, _active_stop_event
    stop_event: threading.Event | None
    sock: socket.socket | None
    with _connection_lock:
        stop_event = _active_stop_event
        sock = _active_socket
        _active_stop_event = None
        _active_socket = None

    if stop_event is not None:
        stop_event.set()
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass

    state.session_ready = False
    state.set_transcription_session(None)
    if show_status:
        state.safe_set(state.menu_status_var, "未接続")


class _WebSocketRejected(RuntimeError):
    pass


def _open_socket(url: str) -> tuple[socket.socket, str, str]:
    parsed = urlsplit(url)
    hostname = parsed.hostname
    if hostname is None:
        raise _WebSocketRejected("websocket host is invalid")

    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "wss" else 80

    raw_socket = socket.create_connection(
        (hostname, port), timeout=BACKEND_HTTP_TIMEOUT_SEC
    )
    raw_socket.settimeout(1.0)

    if parsed.scheme == "wss":
        context = ssl.create_default_context()
        wrapped_socket = context.wrap_socket(raw_socket, server_hostname=hostname)
        wrapped_socket.settimeout(1.0)
        sock = wrapped_socket
    else:
        sock = raw_socket

    target = parsed.path or "/"
    if parsed.query:
        target = f"{target}?{parsed.query}"
    return sock, parsed.netloc, target


def _run_websocket(session: str, serial: int, stop_event: threading.Event) -> None:
    while not stop_event.is_set() and _is_current_serial(serial):
        sock: socket.socket | None = None
        try:
            url = build_ws_url(session)
            sock, host, target = _open_socket(url)
            connection = WSConnection(ConnectionType.CLIENT)
            handshake = connection.send(
                Request(
                    host=host,
                    target=target,
                    extra_headers=[(b"origin", BACKEND_WS_ORIGIN.encode("utf-8"))],
                )
            )
            sock.sendall(handshake)
            _set_active_socket(serial, stop_event, sock)

            message_parts: list[str] = []
            connected = False

            while not stop_event.is_set() and _is_current_serial(serial):
                try:
                    received = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break

                if not received:
                    connection.receive_data(None)
                else:
                    connection.receive_data(received)

                should_break = False
                for event in connection.events():
                    if isinstance(event, AcceptConnection):
                        connected = True
                        state.safe_set(state.menu_status_var, "接続済み")
                        state.safe_set(
                            state.menu_current_session_var,
                            f"現在のセッション: {state.CURRENT_SESSION}",
                        )
                    elif isinstance(event, RejectConnection):
                        raise _WebSocketRejected(
                            f"websocket rejected with status {event.status_code}"
                        )
                    elif isinstance(event, RejectData):
                        continue
                    elif isinstance(event, TextMessage):
                        message_parts.append(event.data)
                        if event.message_finished:
                            message = "".join(message_parts)
                            message_parts.clear()
                            entry = parse_comment_event(message)
                            if entry is None:
                                continue
                            if entry.get("session") != session:
                                continue
                            _on_new_comment(entry)
                    elif isinstance(event, Ping):
                        try:
                            sock.sendall(connection.send(event.response()))
                        except OSError:
                            should_break = True
                    elif isinstance(event, CloseConnection):
                        try:
                            sock.sendall(connection.send(event.response()))
                        except OSError:
                            pass
                        should_break = True

                if should_break or not received:
                    break

            if connected and not stop_event.is_set() and _is_current_serial(serial):
                state.safe_set(state.menu_status_var, "再接続中…")
        except _WebSocketRejected as exc:
            if stop_event.is_set() or not _is_current_serial(serial):
                break
            state.safe_set(state.menu_status_var, "接続失敗")
            try:
                messagebox.showerror("接続エラー", str(exc))
            except Exception:
                pass
            break
        except Exception:
            if stop_event.is_set() or not _is_current_serial(serial):
                break
            state.safe_set(state.menu_status_var, "再接続中…")
        finally:
            if sock is not None:
                _clear_active_socket(serial, sock)
                try:
                    sock.close()
                except Exception:
                    pass

        if stop_event.wait(2.0):
            break


def connect_session(session_name: str):
    serial = _next_connection_serial()

    def _do_connect():
        state.safe_set(state.menu_status_var, "接続中…")
        try:
            state.messages.clear()
            disconnect_session(show_status=False)
            _clear_message_queue()

            normalized_session, messages = fetch_bootstrap(session_name or "default")
            if not _is_current_serial(serial):
                return

            state.CURRENT_SESSION = normalized_session
            state.session_ready = True
            state.set_transcription_session(normalized_session)
            try:
                transcriptions = fetch_transcriptions(normalized_session)
            except BackendApiError:
                transcriptions = []
            except Exception:
                transcriptions = []
            state.replace_transcription_items(transcriptions)
            _on_history(messages)
            state.safe_set(
                state.menu_current_session_var,
                f"現在のセッション: {normalized_session}",
            )
            state.safe_set(state.menu_status_var, "接続済み")

            stop_event = threading.Event()
            with _connection_lock:
                if serial != _connection_serial:
                    stop_event.set()
                    return
                global _active_stop_event
                _active_stop_event = stop_event
            threading.Thread(
                target=_run_websocket,
                args=(normalized_session, serial, stop_event),
                daemon=True,
            ).start()
        except BackendApiError as exc:
            state.session_ready = False
            state.safe_set(state.menu_status_var, "接続失敗")
            try:
                messagebox.showerror("接続エラー", str(exc))
            except Exception:
                pass
        except Exception as exc:
            state.session_ready = False
            state.safe_set(state.menu_status_var, "接続失敗")
            try:
                messagebox.showerror("接続エラー", str(exc))
            except Exception:
                pass

    threading.Thread(target=_do_connect, daemon=True).start()
