from __future__ import annotations

import sys
import unittest
import types
from unittest.mock import patch

if "wsproto" not in sys.modules:
    wsproto_module = types.ModuleType("wsproto")
    wsproto_module.WSConnection = type("WSConnection", (), {})
    sys.modules["wsproto"] = wsproto_module

    connection_module = types.ModuleType("wsproto.connection")
    connection_module.ConnectionType = type("ConnectionType", (), {"CLIENT": "CLIENT"})
    sys.modules["wsproto.connection"] = connection_module

    events_module = types.ModuleType("wsproto.events")
    for name in (
        "AcceptConnection",
        "CloseConnection",
        "Ping",
        "RejectConnection",
        "RejectData",
        "Request",
        "TextMessage",
    ):
        setattr(events_module, name, type(name, (), {}))
    sys.modules["wsproto.events"] = events_module

if "requests" not in sys.modules:
    requests_module = types.ModuleType("requests")
    requests_module.codes = types.SimpleNamespace(ok=200, created=201)
    requests_module.RequestException = type("RequestException", (Exception,), {})
    requests_module.Response = type("Response", (), {})
    requests_module.get = lambda *args, **kwargs: None
    requests_module.post = lambda *args, **kwargs: None
    sys.modules["requests"] = requests_module

from state import app_state as state
from ui.admin_cards import (
    build_comment_history_rows,
    build_comment_history_signature,
    build_transcription_timeline,
)
from ui.file_utils import build_export_filename, sanitize_filename_component
from ui.windows import toggle_comment_window_visibility


class _CommentWindowDouble:
    def __init__(self) -> None:
        self.withdraw_calls = 0
        self.deiconify_calls = 0
        self.attributes_calls: list[tuple[object, ...]] = []
        self.window_id = 321

    def withdraw(self) -> None:
        self.withdraw_calls += 1

    def deiconify(self) -> None:
        self.deiconify_calls += 1

    def attributes(self, *args: object) -> None:
        self.attributes_calls.append(args)

    def winfo_id(self) -> int:
        return self.window_id


class _StringVarDouble:
    def __init__(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


class BuildCommentHistoryRowsTests(unittest.TestCase):
    def test_formats_text_comment_rows(self) -> None:
        messages: list[dict[str, object]] = [
            {
                "name": "Alice",
                "text": "こんにちは",
                "time": "12:34",
                "created_at": "2026-03-10T00:00:00Z",
            }
        ]

        rows = build_comment_history_rows(messages)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, "12:34")
        self.assertEqual(rows[0].name, "Alice")
        self.assertEqual(rows[0].text, "こんにちは")

    def test_skips_stamp_entries_and_applies_fallbacks(self) -> None:
        messages: list[dict[str, object]] = [
            {
                "stamp_url": "/stamps/1.png",
                "name": "stamp user",
                "text": "ignored",
                "time": "09:00",
                "created_at": "2026/03/10 00:00:00",
            },
            {
                "name": "",
                "text": "",
                "time": "",
                "created_at": "",
            },
        ]

        rows = build_comment_history_rows(messages)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].timestamp, "-")
        self.assertEqual(rows[0].name, "名前なし")
        self.assertEqual(rows[0].text, "-")

    def test_signature_ignores_stamp_entries(self) -> None:
        messages: list[dict[str, object]] = [
            {
                "stamp_url": "/stamps/1.png",
                "name": "stamp user",
                "text": "ignored",
                "time": "09:00",
                "created_at": "2026/03/10 00:00:00",
            },
            {
                "name": "Bob",
                "text": "hello",
                "time": "10:15",
                "created_at": "2026-03-10T01:15:00Z",
            },
            {
                "stamp": "thumbs_up",
                "name": "stamp user 2",
                "text": "ignored 2",
                "time": "11:00",
                "created_at": "2026-03-10T02:00:00Z",
            },
        ]

        signature = build_comment_history_signature(messages)

        self.assertEqual(signature, (("10:15", "Bob", "hello", "2026-03-10T01:15:00Z"),))


class BuildTranscriptionTimelineTests(unittest.TestCase):
    def test_sorts_newest_items_first(self) -> None:
        items: list[dict[str, object]] = [
            {
                "id": 1,
                "created_at": "2026-03-10T00:01:00Z",
                "text": "old text",
            },
            {
                "id": 2,
                "created_at": "2026-03-10T00:03:00Z",
                "text": "latest text",
            },
        ]
        events: list[dict[str, object]] = [
            {
                "created_at": "2026-03-10T00:02:00Z",
                "event": "状態更新",
                "detail": "waiting",
            }
        ]

        timeline = build_transcription_timeline(items, events)

        self.assertEqual(
            [entry.kind for entry in timeline],
            ["transcription", "status", "transcription"],
        )
        self.assertEqual(timeline[0].body, "latest text")
        self.assertEqual(timeline[1].body, "waiting")
        self.assertEqual(timeline[2].body, "old text")


class TranscriptionStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._status = dict(state.transcription_status)
        self._items = [dict(item) for item in state.transcription_items]
        self._events = [dict(event) for event in state.transcription_events]
        self._waveform = list(state.transcription_audio_waveform)

    def tearDown(self) -> None:
        state.transcription_status.clear()
        state.transcription_status.update(self._status)
        state.transcription_items.clear()
        state.transcription_items.extend(self._items)
        state.transcription_events.clear()
        state.transcription_events.extend(self._events)
        state.transcription_audio_waveform.clear()
        state.transcription_audio_waveform.extend(self._waveform)

    def test_record_transcription_service_update_hides_upload_events(self) -> None:
        state.set_transcription_session("demo")

        state.record_transcription_service_update(
            {
                "state": "uploading",
                "process_alive": True,
                "session": "demo",
                "last_success_at": None,
                "last_error_at": None,
                "last_error_message": None,
            },
            {
                "event": "保存完了",
                "detail": "hidden",
                "created_at": "2026-03-10T00:00:00Z",
                "session": "demo",
            },
        )
        state.record_transcription_service_update(
            {
                "state": "recording",
                "process_alive": True,
                "session": "demo",
                "last_success_at": None,
                "last_error_at": None,
                "last_error_message": None,
            },
            {
                "event": "録音開始",
                "detail": "visible",
                "created_at": "2026-03-10T00:01:00Z",
                "session": "demo",
            },
        )

        _status, _items, events = state.snapshot_transcription_history()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "録音開始")

    def test_set_transcription_session_clears_waveform(self) -> None:
        state.append_transcription_audio_waveform([0.2, -0.4])

        state.set_transcription_session("demo")

        self.assertEqual(state.snapshot_transcription_audio_waveform(), [])


class ExportFilenameTests(unittest.TestCase):
    def setUp(self) -> None:
        self._current_session = state.CURRENT_SESSION
        self._menu_session_var = state.menu_session_var

    def tearDown(self) -> None:
        state.CURRENT_SESSION = self._current_session
        state.menu_session_var = self._menu_session_var

    def test_sanitize_filename_component_replaces_invalid_characters(self) -> None:
        self.assertEqual(
            sanitize_filename_component('session<>:"/\\|?*name'),
            "session_________name",
        )

    def test_build_export_filename_uses_current_session(self) -> None:
        state.CURRENT_SESSION = "session-01"
        state.menu_session_var = None

        self.assertEqual(build_export_filename(state.CURRENT_SESSION, ".csv"), "session-01.csv")

    def test_build_export_filename_falls_back_to_menu_input(self) -> None:
        state.CURRENT_SESSION = ""
        state.menu_session_var = _StringVarDouble("room/alpha")

        self.assertEqual(
            build_export_filename(state.menu_session_var.get(), "xlsx"),
            "room_alpha.xlsx",
        )


class ToggleCommentWindowVisibilityTests(unittest.TestCase):
    def test_hides_comment_window_when_visible(self) -> None:
        window = _CommentWindowDouble()
        refresh_calls: list[str] = []

        hidden = toggle_comment_window_visibility(
            window,
            hidden=False,
            refresh_layout_callback=lambda: refresh_calls.append("refresh"),
        )

        self.assertTrue(hidden)
        self.assertEqual(window.withdraw_calls, 1)
        self.assertEqual(window.deiconify_calls, 0)
        self.assertEqual(window.attributes_calls, [])
        self.assertEqual(refresh_calls, [])

    def test_restores_comment_window_when_hidden(self) -> None:
        window = _CommentWindowDouble()
        refresh_calls: list[str] = []

        with patch("ui.windows.set_always_on_top") as set_topmost:
            hidden = toggle_comment_window_visibility(
                window,
                hidden=True,
                refresh_layout_callback=lambda: refresh_calls.append("refresh"),
            )

        self.assertFalse(hidden)
        self.assertEqual(refresh_calls, ["refresh"])
        self.assertEqual(window.withdraw_calls, 0)
        self.assertEqual(window.deiconify_calls, 1)
        self.assertEqual(window.attributes_calls, [("-topmost", True)])
        set_topmost.assert_called_once_with(window.window_id)


if __name__ == "__main__":
    unittest.main()
