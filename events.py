from __future__ import annotations

import queue
import threading
from tkinter import messagebox

import app_state as state
from constants import RELAY_SERVER_URL, RELAY_SOCKETIO_PATH
from overlay import should_drop_on_arrival


def _on_history(data):
    if isinstance(data, list):
        filtered = [m for m in data if not should_drop_on_arrival(m)]
        state.message_log.clear()
        state.message_log.extend(filtered)
        while True:
            try:
                state.message_queue.get_nowait()
            except queue.Empty:
                break
        for entry in filtered:
            state.message_queue.put(entry)


def _on_new_comment(entry):
    if isinstance(entry, dict):
        if should_drop_on_arrival(entry):
            return
        state.message_log.append(entry)
        state.message_queue.put(entry)


@state.sio.on("history")
def history_handler(data):
    _on_history(data)


@state.sio.on("new_comment")
def new_comment_handler(data):
    _on_new_comment(data)


@state.sio.on("connect")
def on_connect():
    state.safe_set(state.menu_status_var, "接続済み")
    state.safe_set(
        state.menu_current_session_var, f"現在のセッション: {state.CURRENT_SESSION}"
    )


@state.sio.on("disconnect")
def on_disconnect():
    state.safe_set(state.menu_status_var, "未接続")


def connect_session(session_name: str):
    def _do_connect():
        state.safe_set(state.menu_status_var, "接続中…")
        try:
            if state.sio.connected:
                try:
                    state.sio.disconnect()
                except Exception:
                    pass
            state.CURRENT_SESSION = session_name or "default"
            state.messages.clear()
            while True:
                try:
                    state.message_queue.get_nowait()
                except queue.Empty:
                    break
            url = f"{RELAY_SERVER_URL}?session={state.CURRENT_SESSION}"
            state.sio.connect(url, socketio_path=RELAY_SOCKETIO_PATH)
            state.safe_set(state.menu_status_var, "接続済み")
            state.safe_set(
                state.menu_current_session_var,
                f"現在のセッション: {state.CURRENT_SESSION}",
            )
        except Exception as exc:
            state.safe_set(state.menu_status_var, "接続失敗")
            try:
                messagebox.showerror("接続エラー", str(exc))
            except Exception:
                pass

    threading.Thread(target=_do_connect, daemon=True).start()
