from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence

from backend_api import post_transcription
from constants import TRANSCRIPTION_EXECUTABLE_PATH, TRANSCRIPTION_WORK_DIR


class TranscriptionService:
    def __init__(self, session_provider: Callable[[], str | None]) -> None:
        self._session_provider = session_provider
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            process = self._process
            thread = self._thread
        if process is not None:
            _terminate_process(process)
        if thread is not None:
            thread.join(timeout=3.0)
        with self._lock:
            self._process = None
            self._thread = None

    def _run(self) -> None:
        if not TRANSCRIPTION_EXECUTABLE_PATH.is_file():
            return

        try:
            process = subprocess.Popen(
                [str(TRANSCRIPTION_EXECUTABLE_PATH)],
                cwd=str(TRANSCRIPTION_WORK_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return

        with self._lock:
            self._process = process

        try:
            stream = process.stdout
            if stream is None:
                return
            for raw_line in stream:
                if self._stop_event.is_set():
                    break
                text = _extract_final_text(raw_line)
                if text is None:
                    continue
                session = self._session_provider()
                if session is None:
                    continue
                try:
                    post_transcription(session, text)
                except Exception:
                    continue
        finally:
            _terminate_process(process)
            with self._lock:
                if self._process is process:
                    self._process = None


def _terminate_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=2.0)
    except Exception:
        try:
            process.kill()
        except Exception:
            return


def _extract_final_text(raw_line: str) -> str | None:
    line = raw_line.strip()
    if not line or not line.startswith("{"):
        return None

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None

    return _extract_text_from_payload(payload)


def _extract_text_from_payload(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    if "partial" in payload or "partial_result" in payload:
        return None

    direct_text = payload.get("text")
    if isinstance(direct_text, str):
        normalized = direct_text.strip()
        if normalized:
            return normalized

    alternatives = payload.get("alternatives")
    if isinstance(alternatives, Sequence) and not isinstance(
        alternatives, (str, bytes, bytearray)
    ):
        for alternative in alternatives:
            if not isinstance(alternative, Mapping):
                continue
            alt_text = alternative.get("text")
            if isinstance(alt_text, str):
                normalized = alt_text.strip()
                if normalized:
                    return normalized

    result = payload.get("result")
    if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
        words: list[str] = []
        for item in result:
            if not isinstance(item, Mapping):
                continue
            word = item.get("word")
            if isinstance(word, str):
                normalized = word.strip()
                if normalized:
                    words.append(normalized)
        if words:
            return " ".join(words)

    return None


_service_lock = threading.Lock()
_service: TranscriptionService | None = None


def start_transcription_service(session_provider: Callable[[], str | None]) -> None:
    global _service
    with _service_lock:
        if _service is None:
            _service = TranscriptionService(session_provider)
        _service.start()


def stop_transcription_service() -> None:
    global _service
    with _service_lock:
        service = _service
        _service = None
    if service is not None:
        service.stop()
