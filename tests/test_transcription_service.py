from __future__ import annotations

import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import patch

backend_api_stub = types.ModuleType("services.backend_api")


def _post_transcription_chunk_stub(
    session: str,
    chunk_sequence: int,
    recorded_from: str,
    recorded_to: str,
    audio_path: str,
) -> dict[str, object]:
    return {
        "id": chunk_sequence,
        "session": session,
        "text": f"{session}:{chunk_sequence}",
        "created_at": recorded_to,
    }


backend_api_stub.post_transcription_chunk = _post_transcription_chunk_stub

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

        service = TranscriptionService(lambda: "demo", status_callback, item_callback)
        return service, items, events

    def test_record_chunk_rotates_to_wav_file(self) -> None:
        service, _items, _events = self._build_service()
        cleanup_paths = service._reset_generation("demo")
        self.assertEqual(cleanup_paths, [])

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(transcription_service, "TRANSCRIPTION_TEMP_DIR", Path(temp_dir)), patch.object(
                service,
                "_create_stream",
                return_value=_FakeStream([b"\x01\x02\x03\x04"]),
            ), patch.object(
                transcription_service.time,
                "monotonic",
                side_effect=[0.0, 121.0],
            ):
                chunk = service._record_chunk("demo")

        self.assertIsNotNone(chunk)
        assert chunk is not None
        self.assertEqual(chunk.session, "demo")
        self.assertEqual(chunk.chunk_sequence, 1)
        self.assertTrue(chunk.path.name.endswith(".wav"))

    def test_reset_generation_clears_pending_chunks_and_sequence(self) -> None:
        service, _items, _events = self._build_service()
        with tempfile.TemporaryDirectory() as temp_dir:
            stale_path = Path(temp_dir) / "stale.wav"
            stale_path.write_bytes(b"stale")
            service._enqueue_chunk(
                PendingChunk(
                    generation=0,
                    session="demo",
                    chunk_sequence=1,
                    recorded_from="2026-04-15T00:00:00Z",
                    recorded_to="2026-04-15T00:02:00Z",
                    path=stale_path,
                )
            )
            cleanup_paths = service._reset_generation("other")

        self.assertEqual(cleanup_paths, [stale_path])
        self.assertEqual(service._next_chunk_sequence, 1)

    def test_enqueue_chunk_stops_when_backlog_limit_is_reached(self) -> None:
        service, _items, _events = self._build_service()
        service._reset_generation("demo")
        with tempfile.TemporaryDirectory() as temp_dir:
            for index in range(1, 11):
                overflowed = service._enqueue_chunk(
                    PendingChunk(
                        generation=service._generation,
                        session="demo",
                        chunk_sequence=index,
                        recorded_from="2026-04-15T00:00:00Z",
                        recorded_to="2026-04-15T00:02:00Z",
                        path=Path(temp_dir) / f"{index}.wav",
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
                    path=Path(temp_dir) / "11.wav",
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
            path=Path("retry.wav"),
        )
        service._enqueue_chunk(chunk)

        before = time.monotonic()
        service._mark_chunk_retry(chunk, "network error")
        after = time.monotonic()

        self.assertEqual(chunk.retry_count, 1)
        self.assertGreaterEqual(chunk.next_attempt_at, before + 2.0)
        self.assertLessEqual(chunk.next_attempt_at, after + 2.5)
        self.assertEqual(events[-1]["event"], "送信失敗")

    def test_uploader_notifies_saved_item_and_cleans_up_file(self) -> None:
        service, items, events = self._build_service()
        service._reset_generation("demo")

        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "chunk.wav"
            audio_path.write_bytes(b"RIFF1234WAVEpayload")
            chunk = PendingChunk(
                generation=service._generation,
                session="demo",
                chunk_sequence=1,
                recorded_from="2026-04-15T00:00:00Z",
                recorded_to="2026-04-15T00:02:00Z",
                path=audio_path,
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
                "post_transcription_chunk",
                side_effect=_upload_stub,
            ):
                uploader = threading.Thread(target=service._run_uploader, daemon=True)
                uploader.start()
                uploader.join(timeout=2.0)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["text"], "demo:1")
            self.assertEqual(events[-1]["event"], "保存完了")
            self.assertFalse(audio_path.exists())


if __name__ == "__main__":
    unittest.main()
