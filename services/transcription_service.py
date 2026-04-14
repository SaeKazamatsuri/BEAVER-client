from __future__ import annotations

import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config.constants import (
    TRANSCRIPTION_BACKLOG_LIMIT,
    TRANSCRIPTION_CHANNELS,
    TRANSCRIPTION_CHUNK_DURATION_SEC,
    TRANSCRIPTION_READ_FRAMES,
    TRANSCRIPTION_SAMPLE_RATE_HZ,
    TRANSCRIPTION_SAMPLE_WIDTH_BYTES,
    TRANSCRIPTION_TEMP_DIR,
)
from services.backend_api import post_transcription_chunk

try:
    import sounddevice
except ImportError:  # pragma: no cover - exercised through runtime guard
    sounddevice = None

StatusCallback = Callable[[dict[str, object], dict[str, object] | None], None]
ItemCallback = Callable[[dict[str, object]], None]

_MISSING = object()


@dataclass(slots=True)
class PendingChunk:
    generation: int
    session: str
    chunk_sequence: int
    recorded_from: str
    recorded_to: str
    path: Path
    retry_count: int = 0
    next_attempt_at: float = 0.0


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _cleanup_path(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def _retry_delay_seconds(retry_count: int) -> float:
    return min(60.0, float(2 ** min(retry_count, 5)))


class TranscriptionService:
    def __init__(
        self,
        session_provider: Callable[[], str | None],
        status_callback: StatusCallback | None,
        item_callback: ItemCallback | None,
    ) -> None:
        self._session_provider = session_provider
        self._status_callback = status_callback
        self._item_callback = item_callback
        self._stop_event = threading.Event()
        self._controller_thread: threading.Thread | None = None
        self._uploader_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._queue_condition = threading.Condition()
        self._pending_chunks: deque[PendingChunk] = deque()
        self._generation = 0
        self._next_chunk_sequence = 1
        self._paused_session: str | None = None
        self._status_snapshot: dict[str, object] = {
            "state": "idle",
            "process_alive": False,
            "session": "",
            "last_started_at": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error_message": None,
        }

    def start(self) -> None:
        with self._lock:
            if self._controller_thread is not None and self._controller_thread.is_alive():
                return
            self._stop_event.clear()
            self._controller_thread = threading.Thread(
                target=self._run_controller,
                daemon=True,
            )
            self._uploader_thread = threading.Thread(
                target=self._run_uploader,
                daemon=True,
            )
        started_at = _now_iso()
        self._publish_status(
            state="starting",
            process_alive=False,
            session=self._current_session(),
            last_started_at=started_at,
            event_name="起動開始",
            event_detail="録音サービスを起動しています。",
            event_time=started_at,
        )
        TRANSCRIPTION_TEMP_DIR.mkdir(parents=True, exist_ok=True)
        controller_thread = self._controller_thread
        uploader_thread = self._uploader_thread
        if controller_thread is not None:
            controller_thread.start()
        if uploader_thread is not None:
            uploader_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            controller_thread = self._controller_thread
            uploader_thread = self._uploader_thread
        with self._queue_condition:
            self._queue_condition.notify_all()
        if controller_thread is not None:
            controller_thread.join(timeout=3.0)
        if uploader_thread is not None:
            uploader_thread.join(timeout=3.0)

        cleanup_paths = self._reset_generation(None)
        for path in cleanup_paths:
            _cleanup_path(path)

        with self._lock:
            self._controller_thread = None
            self._uploader_thread = None

        stopped_at = _now_iso()
        self._publish_status(
            state="stopped",
            process_alive=False,
            session=self._current_session(),
            event_name="停止",
            event_detail="録音サービスを停止しました。",
            event_time=stopped_at,
        )

    def _run_controller(self) -> None:
        active_session: str | None = None
        last_idle_published = False

        while not self._stop_event.is_set():
            session = self._current_session()
            if session is None:
                if active_session is not None:
                    cleanup_paths = self._reset_generation(None)
                    for path in cleanup_paths:
                        _cleanup_path(path)
                    active_session = None
                if not last_idle_published:
                    self._publish_status(
                        state="idle",
                        process_alive=False,
                        session=None,
                        event_name="待機中",
                        event_detail="セッション接続待ちです。",
                        event_time=_now_iso(),
                    )
                    last_idle_published = True
                self._stop_event.wait(0.2)
                continue

            if session != active_session:
                cleanup_paths = self._reset_generation(session)
                for path in cleanup_paths:
                    _cleanup_path(path)
                active_session = session
                last_idle_published = False
                self._publish_status(
                    state="recording",
                    process_alive=True,
                    session=session,
                    last_error_at=None,
                    last_error_message=None,
                    event_name="録音開始",
                    event_detail="2分チャンク録音を開始しました。",
                    event_time=_now_iso(),
                )

            if self._is_paused(session):
                self._stop_event.wait(0.2)
                continue

            try:
                completed_chunk = self._record_chunk(session)
            except Exception as exc:
                failed_at = _now_iso()
                self._publish_status(
                    state="error",
                    process_alive=False,
                    session=session,
                    last_error_at=failed_at,
                    last_error_message=str(exc),
                    event_name="録音失敗",
                    event_detail=f"録音に失敗しました: {exc}",
                    event_time=failed_at,
                )
                self._stop_event.wait(1.0)
                continue

            if completed_chunk is None:
                continue

            overflowed = self._enqueue_chunk(completed_chunk)
            if overflowed:
                _cleanup_path(completed_chunk.path)
                self._publish_status(
                    state="error",
                    process_alive=False,
                    session=session,
                    last_error_at=_now_iso(),
                    last_error_message="送信待ちチャンクが上限を超えました。",
                    event_name="待機超過",
                    event_detail="未送信チャンクが上限を超えたため録音を一時停止しました。",
                    event_time=_now_iso(),
                )
                continue

            self._publish_status(
                state="recording",
                process_alive=True,
                session=session,
                event_name="録音完了",
                event_detail="2分音声を送信キューへ追加しました。",
                event_time=completed_chunk.recorded_to,
            )

    def _run_uploader(self) -> None:
        while not self._stop_event.is_set():
            chunk = self._wait_for_next_chunk()
            if chunk is None:
                continue

            self._publish_status(
                state="uploading",
                process_alive=True,
                session=chunk.session,
                event_name="送信開始",
                event_detail="音声チャンクをバックエンドへ送信しています。",
                event_time=_now_iso(),
            )

            try:
                item = post_transcription_chunk(
                    chunk.session,
                    chunk.chunk_sequence,
                    chunk.recorded_from,
                    chunk.recorded_to,
                    str(chunk.path),
                )
            except Exception as exc:
                self._mark_chunk_retry(chunk, str(exc))
                continue

            self._pop_uploaded_chunk(chunk)
            created_at = str(item.get("created_at") or _now_iso())
            self._publish_status(
                state="recording",
                process_alive=True,
                session=chunk.session,
                last_success_at=created_at,
                last_error_at=None,
                last_error_message=None,
                event_name="保存完了",
                event_detail="文字起こしをバックエンドへ保存しました。",
                event_time=created_at,
            )
            self._notify_item(item)

    def _record_chunk(self, session: str) -> PendingChunk | None:
        generation, chunk_sequence = self._snapshot_recording_state(session)
        path = TRANSCRIPTION_TEMP_DIR / f"{session}-{generation}-{chunk_sequence}.wav"
        recorded_from = _now_iso()
        deadline = time.monotonic() + TRANSCRIPTION_CHUNK_DURATION_SEC

        with self._create_stream() as stream:
            with wave.open(str(path), "wb") as wav_file:
                wav_file.setnchannels(TRANSCRIPTION_CHANNELS)
                wav_file.setsampwidth(TRANSCRIPTION_SAMPLE_WIDTH_BYTES)
                wav_file.setframerate(TRANSCRIPTION_SAMPLE_RATE_HZ)

                while not self._stop_event.is_set():
                    current_session = self._current_session()
                    if current_session != session:
                        _cleanup_path(path)
                        return None
                    if self._is_generation_stale(generation, session):
                        _cleanup_path(path)
                        return None

                    audio_bytes, _overflowed = stream.read(TRANSCRIPTION_READ_FRAMES)
                    wav_file.writeframes(audio_bytes)

                    if time.monotonic() >= deadline:
                        break

        if self._stop_event.is_set() or self._current_session() != session:
            _cleanup_path(path)
            return None

        recorded_to = _now_iso()
        return PendingChunk(
            generation=generation,
            session=session,
            chunk_sequence=chunk_sequence,
            recorded_from=recorded_from,
            recorded_to=recorded_to,
            path=path,
        )

    def _create_stream(self):
        if sounddevice is None:
            raise RuntimeError("sounddevice がインストールされていません。")
        return sounddevice.RawInputStream(
            samplerate=TRANSCRIPTION_SAMPLE_RATE_HZ,
            channels=TRANSCRIPTION_CHANNELS,
            dtype="int16",
            blocksize=TRANSCRIPTION_READ_FRAMES,
        )

    def _snapshot_recording_state(self, session: str) -> tuple[int, int]:
        with self._queue_condition:
            if self._paused_session == session:
                raise RuntimeError("送信待ちが上限を超えているため録音を停止中です。")
            return self._generation, self._next_chunk_sequence

    def _is_generation_stale(self, generation: int, session: str) -> bool:
        with self._queue_condition:
            return generation != self._generation or self._paused_session == session

    def _enqueue_chunk(self, chunk: PendingChunk) -> bool:
        with self._queue_condition:
            if chunk.generation != self._generation:
                return False
            if len(self._pending_chunks) >= TRANSCRIPTION_BACKLOG_LIMIT:
                self._paused_session = chunk.session
                return True
            self._pending_chunks.append(chunk)
            self._next_chunk_sequence = chunk.chunk_sequence + 1
            self._queue_condition.notify_all()
            return False

    def _wait_for_next_chunk(self) -> PendingChunk | None:
        with self._queue_condition:
            while not self._stop_event.is_set():
                if not self._pending_chunks:
                    self._queue_condition.wait(timeout=0.5)
                    continue
                chunk = self._pending_chunks[0]
                if chunk.generation != self._generation:
                    stale_chunk = self._pending_chunks.popleft()
                    _cleanup_path(stale_chunk.path)
                    continue
                now = time.monotonic()
                if chunk.next_attempt_at > now:
                    self._queue_condition.wait(timeout=chunk.next_attempt_at - now)
                    continue
                return chunk
        return None

    def _mark_chunk_retry(self, chunk: PendingChunk, error_message: str) -> None:
        failed_at = _now_iso()
        with self._queue_condition:
            if self._pending_chunks and self._pending_chunks[0] is chunk:
                chunk.retry_count += 1
                chunk.next_attempt_at = time.monotonic() + _retry_delay_seconds(
                    chunk.retry_count
                )
                self._queue_condition.notify_all()
        self._publish_status(
            state="error",
            process_alive=True,
            session=chunk.session,
            last_error_at=failed_at,
            last_error_message=error_message,
            event_name="送信失敗",
            event_detail=f"音声チャンクの送信に失敗しました: {error_message}",
            event_time=failed_at,
        )

    def _pop_uploaded_chunk(self, chunk: PendingChunk) -> None:
        with self._queue_condition:
            if self._pending_chunks and self._pending_chunks[0] is chunk:
                self._pending_chunks.popleft()
            if self._paused_session == chunk.session and (
                len(self._pending_chunks) < TRANSCRIPTION_BACKLOG_LIMIT
            ):
                self._paused_session = None
                self._queue_condition.notify_all()
                self._publish_status(
                    state="recording",
                    process_alive=True,
                    session=chunk.session,
                    event_name="録音再開",
                    event_detail="送信待ちが解消したため録音を再開します。",
                    event_time=_now_iso(),
                )
        _cleanup_path(chunk.path)

    def _is_paused(self, session: str) -> bool:
        with self._queue_condition:
            return self._paused_session == session

    def _reset_generation(self, session: str | None) -> list[Path]:
        with self._queue_condition:
            self._generation += 1
            self._next_chunk_sequence = 1
            self._paused_session = None
            cleanup_paths = [chunk.path for chunk in self._pending_chunks]
            self._pending_chunks.clear()
            self._queue_condition.notify_all()
            return cleanup_paths

    def _notify_item(self, item: dict[str, object]) -> None:
        callback = self._item_callback
        if callback is None:
            return
        try:
            callback(dict(item))
        except Exception:
            return

    def _publish_status(
        self,
        *,
        state: str | None = None,
        process_alive: bool | None = None,
        session: str | None | object = _MISSING,
        last_started_at: str | None | object = _MISSING,
        last_success_at: str | None | object = _MISSING,
        last_error_at: str | None | object = _MISSING,
        last_error_message: str | None | object = _MISSING,
        event_name: str | None = None,
        event_detail: str | None = None,
        event_time: str | None = None,
    ) -> None:
        with self._lock:
            if state is not None:
                self._status_snapshot["state"] = state
            if process_alive is not None:
                self._status_snapshot["process_alive"] = process_alive
            if session is not _MISSING:
                self._status_snapshot["session"] = session or ""
            if last_started_at is not _MISSING:
                self._status_snapshot["last_started_at"] = last_started_at
            if last_success_at is not _MISSING:
                self._status_snapshot["last_success_at"] = last_success_at
            if last_error_at is not _MISSING:
                self._status_snapshot["last_error_at"] = last_error_at
            if last_error_message is not _MISSING:
                self._status_snapshot["last_error_message"] = last_error_message
            snapshot = dict(self._status_snapshot)

        callback = self._status_callback
        if callback is None:
            return

        event: dict[str, object] | None = None
        if event_name is not None:
            event = {
                "kind": "status",
                "event": event_name,
                "detail": event_detail or "",
                "created_at": event_time or _now_iso(),
                "session": str(snapshot.get("session") or ""),
            }

        try:
            callback(snapshot, event)
        except Exception:
            return

    def _current_session(self) -> str | None:
        session = self._session_provider()
        if session is None:
            return None
        normalized = session.strip()
        return normalized or None


_service_lock = threading.Lock()
_service: TranscriptionService | None = None


def start_transcription_service(
    session_provider: Callable[[], str | None],
    status_callback: StatusCallback | None = None,
    item_callback: ItemCallback | None = None,
) -> None:
    global _service
    with _service_lock:
        if _service is None:
            _service = TranscriptionService(
                session_provider,
                status_callback,
                item_callback,
            )
        _service.start()


def stop_transcription_service() -> None:
    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        service.stop()
