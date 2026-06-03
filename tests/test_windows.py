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
    build_poll_results_view,
    build_transcription_timeline,
)
from ui.file_utils import build_export_filename, sanitize_filename_component
from ui.windows import toggle_comment_window_visibility
from services.backend_api import (
    BackendApiError,
    normalize_comment_item,
    normalize_poll_item,
    normalize_poll_results,
    parse_reaction_update_event,
)


class ReactionUpdateParsingTests(unittest.TestCase):
    def test_parses_bookmark_count(self) -> None:
        message = (
            '{"type":"comment.reactions.updated","payload":{"session":"demo",'
            '"commentId":7,"reactions":[{"reactionKey":"bookmark","count":3,'
            '"reactedByCurrentUser":false}]}}'
        )
        result = parse_reaction_update_event(message)
        self.assertEqual(
            result, {"session": "demo", "comment_id": 7, "bookmark_count": 3}
        )

    def test_empty_reactions_means_zero(self) -> None:
        message = (
            '{"type":"comment.reactions.updated","payload":{"session":"demo",'
            '"commentId":7,"reactions":[]}}'
        )
        result = parse_reaction_update_event(message)
        self.assertEqual(result, {"session": "demo", "comment_id": 7, "bookmark_count": 0})

    def test_ignores_other_event_types(self) -> None:
        self.assertIsNone(
            parse_reaction_update_event('{"type":"comment.created","payload":{}}')
        )

    def test_normalize_comment_item_extracts_bookmark_count(self) -> None:
        item = normalize_comment_item(
            {
                "id": 1,
                "session": "demo",
                "name": "A",
                "realName": "A",
                "text": "hi",
                "time": "10:00",
                "stamp": None,
                "stampPath": None,
                "source": "textbox",
                "createdAt": "2026-03-10T00:00:00Z",
                "reactions": [
                    {"reactionKey": "bookmark", "count": 2, "reactedByCurrentUser": True}
                ],
            }
        )
        self.assertEqual(item["bookmark_count"], 2)


class PollNormalizationTests(unittest.TestCase):
    def test_normalize_poll_item(self) -> None:
        item = normalize_poll_item(
            {
                "id": 5,
                "session": "demo",
                "question": "好きな色は？",
                "options": ["赤", "青", "緑"],
                "durationSec": 20,
                "createdAt": "2026-03-10T00:00:00Z",
            }
        )
        self.assertEqual(
            item,
            {
                "id": 5,
                "session": "demo",
                "question": "好きな色は？",
                "options": ["赤", "青", "緑"],
                "duration_sec": 20,
                "created_at": "2026-03-10T00:00:00Z",
            },
        )

    def test_normalize_poll_results(self) -> None:
        results = normalize_poll_results(
            {
                "pollId": 5,
                "runId": 9,
                "question": "好きな色は？",
                "options": ["赤", "青"],
                "durationSec": 20,
                "startedAt": "2026-03-10T00:00:00.000Z",
                "deliveredCount": 4,
                "answerCount": 2,
                "answerRate": 0.5,
                "averageResponseMs": 1500.0,
                "optionCounts": [1, 1],
                "answers": [
                    {
                        "name": "Alice",
                        "realName": "Alice Example",
                        "optionIndex": 0,
                        "responseMs": 1000,
                        "clientElapsedMs": 900,
                        "createdAt": "2026-03-10T00:00:01Z",
                    }
                ],
            }
        )
        self.assertEqual(results["poll_id"], 5)
        self.assertEqual(results["run_id"], 9)
        self.assertEqual(results["option_counts"], [1, 1])
        self.assertEqual(results["answer_rate"], 0.5)
        self.assertEqual(results["average_response_ms"], 1500.0)
        self.assertEqual(results["answers"][0]["option_index"], 0)
        self.assertEqual(results["answers"][0]["client_elapsed_ms"], 900)

    def test_normalize_poll_results_allows_null_average(self) -> None:
        results = normalize_poll_results(
            {
                "pollId": 1,
                "runId": 1,
                "question": "Q",
                "options": ["A", "B"],
                "durationSec": 10,
                "startedAt": "2026-03-10T00:00:00.000Z",
                "deliveredCount": 0,
                "answerCount": 0,
                "answerRate": 0.0,
                "averageResponseMs": None,
                "optionCounts": [0, 0],
                "answers": [],
            }
        )
        self.assertIsNone(results["average_response_ms"])

    def test_normalize_poll_item_rejects_non_string_option(self) -> None:
        with self.assertRaises(BackendApiError):
            normalize_poll_item(
                {
                    "id": 1,
                    "session": "demo",
                    "question": "Q",
                    "options": ["A", 2],
                    "durationSec": 10,
                    "createdAt": "2026-03-10T00:00:00Z",
                }
            )


class BuildPollResultsViewTests(unittest.TestCase):
    def test_builds_view_with_percentages(self) -> None:
        view = build_poll_results_view(
            {
                "question": "好きな色は？",
                "options": ["赤", "青", "緑"],
                "option_counts": [3, 1, 0],
                "answer_count": 4,
                "delivered_count": 5,
                "answer_rate": 0.8,
                "average_response_ms": 2000.0,
                "answers": [
                    {"name": "Alice", "option_index": 0, "response_ms": 1500},
                    {"name": "Bob", "option_index": 2, "response_ms": 2500},
                ],
            }
        )
        self.assertEqual(view.question, "好きな色は？")
        self.assertEqual(len(view.options), 3)
        self.assertEqual(view.options[0].count, 3)
        self.assertAlmostEqual(view.options[0].percentage, 75.0)
        self.assertAlmostEqual(view.answer_rate_percent, 80.0)
        self.assertEqual(view.delivered_count, 5)
        self.assertEqual(view.answer_count, 4)
        self.assertAlmostEqual(view.average_response_sec, 2.0)
        self.assertEqual(view.answers[0].option_label, "赤")
        self.assertEqual(view.answers[1].option_label, "緑")
        self.assertAlmostEqual(view.answers[0].response_sec, 1.5)

    def test_handles_zero_answers(self) -> None:
        view = build_poll_results_view(
            {
                "question": "Q",
                "options": ["A", "B"],
                "option_counts": [0, 0],
                "answer_count": 0,
                "delivered_count": 0,
                "answer_rate": 0.0,
                "average_response_ms": None,
                "answers": [],
            }
        )
        self.assertEqual(view.options[0].percentage, 0.0)
        self.assertIsNone(view.average_response_sec)
        self.assertEqual(view.answers, [])


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

    def test_bookmark_order_sorts_by_count_desc(self) -> None:
        messages: list[dict[str, object]] = [
            {
                "name": "A",
                "text": "few",
                "time": "10:00",
                "created_at": "2026-03-10T01:00:00Z",
                "bookmark_count": 1,
            },
            {
                "name": "B",
                "text": "many",
                "time": "10:01",
                "created_at": "2026-03-10T01:01:00Z",
                "bookmark_count": 5,
            },
            {
                "name": "C",
                "text": "none",
                "time": "10:02",
                "created_at": "2026-03-10T01:02:00Z",
            },
        ]

        rows = build_comment_history_rows(messages, order="bookmark")

        self.assertEqual([row.text for row in rows], ["many", "few", "none"])
        self.assertEqual(rows[0].bookmarks, 5)

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

        self.assertEqual(
            signature, (("10:15", "Bob", "hello", "2026-03-10T01:15:00Z", 0),)
        )


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
