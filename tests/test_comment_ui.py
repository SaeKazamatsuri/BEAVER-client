from __future__ import annotations

import unittest

from ui.comment_ui import (
    _card_total_height,
    SOFT_WRAP_MARKER,
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


if __name__ == "__main__":
    unittest.main()
