from __future__ import annotations

import unittest
import tkinter as tk

from state import app_state as state
from ui.admin_cards import (
    build_comment_history_rows,
    build_comment_history_signature,
    build_transcription_timeline,
)
from ui.file_utils import build_export_filename, sanitize_filename_component


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
        interpreter = tk.Tcl()
        state.CURRENT_SESSION = ""
        state.menu_session_var = tk.StringVar(master=interpreter, value="room/alpha")

        self.assertEqual(
            build_export_filename(state.menu_session_var.get(), "xlsx"),
            "room_alpha.xlsx",
        )


if __name__ == "__main__":
    unittest.main()
