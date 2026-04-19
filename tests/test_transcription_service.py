from __future__ import annotations

import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

backend_api_stub = types.ModuleType("services.backend_api")


def _upload_transcription_chunk_ws_stub(
    session: str,
    chunk_sequence: int,
    recorded_from: str,
    recorded_to: str,
    audio_bytes: bytes,
) -> dict[str, object]:
    if not audio_bytes.startswith(b"RIFF"):
        raise AssertionError("audio bytes must be WAV data")
    return {
        "id": chunk_sequence,
        "session": session,
        "text": f"{session}:{chunk_sequence}",
        "created_at": recorded_to,
    }


backend_api_stub.upload_transcription_chunk_ws = _upload_transcription_chunk_ws_stub

with patch.dict(sys.modules, {"services.backend_api": backend_api_stub}):
    from services import transcription_service
    from services.transcription_service import PendingChunk, TranscriptionService


class _FakeStream:
    def __init__(self, payloads: list[bytes]) -> None:
        self._payloads = list(payloads)

    def __enter__(self) -> "_FakeStream":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def read(self, _frames: int) -> tuple[bytes, bool]:
        payload = self._payloads.pop(0) if self._payloads else b"\x00\x00"
        return payload, False


class TranscriptionServiceTests(unittest.TestCase):
    def _build_service(self) -> tuple[TranscriptionService, list[dict[str, object]], list[dict[str, object] | None]]:
        items: list[dict[str, object]] = []
        events: list[dict[str, object] | None] = []

        def status_callback(snapshot: dict[str, object], event: dict[str, object] | None) -> None:
            events.append(event)

        def item_callback(item: dict[str, object]) -> None:
            items.append(item)

        service = TranscriptionService(
            lambda: "demo",
            status_callback,
            item_callback,
            None,
        )
        return service, items, events

    def test_record_chunk_rotates_to_wav_file(self) -> None:
        service, _items, _events = self._build_service()
        service._reset_generation("demo")

        with patch.object(
            service,
            "_create_stream",
            return_value=_FakeStream([b"\x01\x02\x03\x04"]),
        ), patch.object(
            transcription_service.time,
            "monotonic",
            side_effect=[0.0, 181.0],
        ):
            chunk = service._record_chunk("demo")

        self.assertIsNotNone(chunk)
        assert chunk is not None
        self.assertEqual(chunk.session, "demo")
        self.assertEqual(chunk.chunk_sequence, 1)
        self.assertTrue(chunk.audio_bytes.startswith(b"RIFF"))
        self.assertIn(b"WAVE", chunk.audio_bytes)

    def test_reset_generation_clears_pending_chunks_and_sequence(self) -> None:
        service, _items, _events = self._build_service()
        service._enqueue_chunk(
            PendingChunk(
                generation=0,
                session="demo",
                chunk_sequence=1,
                recorded_from="2026-04-15T00:00:00Z",
                recorded_to="2026-04-15T00:02:00Z",
                audio_bytes=b"RIFF1234WAVEpayload",
            )
        )
        service._reset_generation("other")
        self.assertEqual(service._next_chunk_sequence, 1)

    def test_enqueue_chunk_stops_when_backlog_limit_is_reached(self) -> None:
        service, _items, _events = self._build_service()
        service._reset_generation("demo")
        for index in range(1, 11):
            overflowed = service._enqueue_chunk(
                PendingChunk(
                    generation=service._generation,
                    session="demo",
                    chunk_sequence=index,
                    recorded_from="2026-04-15T00:00:00Z",
                    recorded_to="2026-04-15T00:02:00Z",
                    audio_bytes=b"RIFF1234WAVEpayload",
                )
            )
            self.assertFalse(overflowed)

        overflowed = service._enqueue_chunk(
            PendingChunk(
                generation=service._generation,
                session="demo",
                chunk_sequence=11,
                recorded_from="2026-04-15T00:00:00Z",
                recorded_to="2026-04-15T00:02:00Z",
                audio_bytes=b"RIFF1234WAVEpayload",
            )
        )

        self.assertTrue(overflowed)
        self.assertEqual(service._paused_session, "demo")

    def test_mark_chunk_retry_sets_exponential_backoff(self) -> None:
        service, _items, events = self._build_service()
        service._reset_generation("demo")
        chunk = PendingChunk(
            generation=service._generation,
            session="demo",
            chunk_sequence=1,
            recorded_from="2026-04-15T00:00:00Z",
            recorded_to="2026-04-15T00:02:00Z",
            audio_bytes=b"RIFF1234WAVEpayload",
        )
        service._enqueue_chunk(chunk)

        before = time.monotonic()
        service._mark_chunk_retry(chunk, "network error")
        after = time.monotonic()

        self.assertEqual(chunk.retry_count, 1)
        self.assertGreaterEqual(chunk.next_attempt_at, before + 2.0)
        self.assertLessEqual(chunk.next_attempt_at, after + 2.5)
        self.assertEqual(events[-1]["event"], "送信失敗")

    def test_uploader_notifies_saved_item(self) -> None:
        service, items, events = self._build_service()
        service._reset_generation("demo")
        chunk = PendingChunk(
            generation=service._generation,
            session="demo",
            chunk_sequence=1,
            recorded_from="2026-04-15T00:00:00Z",
            recorded_to="2026-04-15T00:02:00Z",
            audio_bytes=b"RIFF1234WAVEpayload",
        )
        service._enqueue_chunk(chunk)

        def _upload_stub(*_args: object, **_kwargs: object) -> dict[str, object]:
            service._stop_event.set()
            return {
                "id": 1,
                "session": "demo",
                "text": "demo:1",
                "created_at": "2026-04-15T00:02:00Z",
            }

        with patch.object(
            transcription_service,
            "upload_transcription_chunk_ws",
            side_effect=_upload_stub,
        ):
            uploader = threading.Thread(target=service._run_uploader, daemon=True)
            uploader.start()
            uploader.join(timeout=2.0)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "demo:1")
        self.assertEqual(events[-1]["event"], "保存完了")

    def test_sample_waveform_points_normalizes_pcm_audio(self) -> None:
        pcm = (
            b"\x00\x00"
            + b"\x00\x40"
            + b"\x00\xc0"
            + b"\xff\x7f"
            + b"\x00\x80"
        )

        points = transcription_service._sample_waveform_points(pcm, max_points=5)

        self.assertEqual(len(points), 5)
        self.assertAlmostEqual(points[0], 0.0)
        self.assertGreater(points[1], 0.49)
        self.assertLess(points[2], -0.49)
        self.assertAlmostEqual(points[3], 32767.0 / 32768.0)
        self.assertEqual(points[4], -1.0)


if __name__ == "__main__":
    unittest.main()
