from __future__ import annotations

import unittest
from datetime import datetime

from ui.comment_ui import (
    _card_total_height,
    _extract_ai_question_state,
    SOFT_WRAP_MARKER,
    AI_QUESTION_LIFETIME_SEC,
    CommentEntry,
    comment_entry_from_message,
    insert_soft_wraps,
)


class InsertSoftWrapsTests(unittest.TestCase):
    def test_inserts_marker_every_sixteen_characters_for_long_ascii_tokens(self) -> None:
        text = "abcdefghijklmnop1234567890qrstuv"

        wrapped = insert_soft_wraps(text)

        self.assertEqual(
            wrapped,
            "abcdefghijklmnop"
            + SOFT_WRAP_MARKER
            + "1234567890qrstuv",
        )


class CardHeightTests(unittest.TestCase):
    def test_card_total_height_is_relative_to_top(self) -> None:
        first = _card_total_height(
            card_top=10,
            card_bottom=104,
            shadow_offset_y=6,
            bottom_padding=6,
        )
        second = _card_total_height(
            card_top=200,
            card_bottom=294,
            shadow_offset_y=6,
            bottom_padding=6,
        )

        self.assertEqual(first, 106)
        self.assertEqual(second, 106)


class CommentEntryFromMessageTests(unittest.TestCase):
    def test_returns_none_for_stamp_messages(self) -> None:
        message: dict[str, object] = {
            "id": 1,
            "session": "default",
            "name": "Alice",
            "text": "",
            "time": "12:34",
            "stamp_url": "/stamps/1.png",
            "created_at": "2026-03-10T00:00:00Z",
        }

        result = comment_entry_from_message(message)

        self.assertIsNone(result)

    def test_converts_text_message_to_comment_entry(self) -> None:
        message: dict[str, object] = {
            "id": 2,
            "session": "default",
            "name": "Bob",
            "text": "hello world",
            "time": "12:35",
            "created_at": "2026-03-10T00:01:00Z",
            "_from_history": True,
        }

        result = comment_entry_from_message(message)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.id, 2)
        self.assertEqual(result.session, "default")
        self.assertEqual(result.name, "Bob")
        self.assertEqual(result.text, "hello world")
        self.assertEqual(result.time, "12:35")
        self.assertEqual(result.created_at, "2026-03-10T00:01:00Z")
        self.assertTrue(result.from_history)
        self.assertIsNone(result.stamp_url)


class ExtractAiQuestionStateTests(unittest.TestCase):
    def _timestamp(self, value: str) -> float:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()

    def _entry(
        self,
        *,
        entry_id: int,
        created_at: str,
        source: str | None,
        text: str,
    ) -> CommentEntry:
        return CommentEntry(
            id=entry_id,
            session="default",
            name="AI",
            text=text,
            time="12:35",
            stamp_url=None,
            created_at=created_at,
            from_history=True,
            source=source,
        )

    def test_restores_latest_active_ai_question_and_count(self) -> None:
        comments = [
            self._entry(
                entry_id=1,
                created_at="2026-03-10T00:00:00Z",
                source="ai_question",
                text="same question",
            ),
            self._entry(
                entry_id=2,
                created_at="2026-03-10T00:01:00Z",
                source="textbox",
                text="normal",
            ),
            self._entry(
                entry_id=3,
                created_at="2026-03-10T00:04:30Z",
                source="ai_question",
                text="same question",
            ),
        ]

        entry, count, expiration = _extract_ai_question_state(
            comments,
            now=self._timestamp("2026-03-10T00:05:00Z"),
        )

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.id, 3)
        self.assertEqual(count, 2)
        self.assertEqual(
            expiration,
            self._timestamp("2026-03-10T00:04:30Z") + AI_QUESTION_LIFETIME_SEC,
        )

    def test_resets_count_when_ai_question_text_changes(self) -> None:
        comments = [
            self._entry(
                entry_id=20,
                created_at="2026-03-10T00:00:00Z",
                source="ai_question",
                text="first question",
            ),
            self._entry(
                entry_id=21,
                created_at="2026-03-10T00:03:00Z",
                source="ai_question",
                text="second question",
            ),
        ]

        entry, count, expiration = _extract_ai_question_state(
            comments,
            now=self._timestamp("2026-03-10T00:03:30Z"),
        )

        self.assertIsNotNone(entry)
        assert entry is not None
        self.assertEqual(entry.id, 21)
        self.assertEqual(count, 1)
        self.assertEqual(
            expiration,
            self._timestamp("2026-03-10T00:03:00Z") + AI_QUESTION_LIFETIME_SEC,
        )

    def test_discards_expired_ai_question_history(self) -> None:
        comments = [
            self._entry(
                entry_id=10,
                created_at="2026-03-10T00:00:00Z",
                source="ai_question",
                text="expired",
            )
        ]

        entry, count, expiration = _extract_ai_question_state(
            comments,
            now=self._timestamp("2026-03-10T00:00:00Z") + AI_QUESTION_LIFETIME_SEC + 1.0,
        )

        self.assertIsNone(entry)
        self.assertEqual(count, 0)
        self.assertEqual(expiration, 0.0)


if __name__ == "__main__":
    unittest.main()
