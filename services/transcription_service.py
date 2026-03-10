from __future__ import annotations

import csv
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone

from config.constants import (
    TRANSCRIPTION_CSV_PATH,
    TRANSCRIPTION_EXECUTABLE_PATH,
    TRANSCRIPTION_WORK_DIR,
)
from services.backend_api import post_transcription

StatusCallback = Callable[[dict[str, object], dict[str, object] | None], None]
ItemCallback = Callable[[dict[str, object]], None]

_MISSING = object()


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _build_hidden_process_options() -> tuple[subprocess.STARTUPINFO | None, int]:
    if sys.platform != "win32":
        return None, 0

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return startupinfo, subprocess.CREATE_NO_WINDOW


def _start_transcription_process() -> subprocess.Popen[str]:
    command = [
        str(TRANSCRIPTION_EXECUTABLE_PATH),
        "--output-csv",
        str(TRANSCRIPTION_CSV_PATH),
        "--quiet",
    ]
    startupinfo, creationflags = _build_hidden_process_options()
    if startupinfo is None:
        return subprocess.Popen(
            command,
            cwd=str(TRANSCRIPTION_WORK_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    return subprocess.Popen(
        command,
        cwd=str(TRANSCRIPTION_WORK_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        startupinfo=startupinfo,
        creationflags=creationflags,
    )


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
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
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
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
        started_at = _now_iso()
        self._publish_status(
            state="starting",
            process_alive=False,
            session=self._current_session(),
            last_started_at=started_at,
            event_name="起動開始",
            event_detail="文字起こしプロセスを起動しています。",
            event_time=started_at,
        )
        thread = self._thread
        if thread is not None:
            thread.start()

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
        stopped_at = _now_iso()
        self._publish_status(
            state="stopped",
            process_alive=False,
            session=self._current_session(),
            event_name="停止",
            event_detail="文字起こしサービスを停止しました。",
            event_time=stopped_at,
        )

    def _run(self) -> None:
        current_session = self._current_session()
        if not TRANSCRIPTION_EXECUTABLE_PATH.is_file():
            missing_at = _now_iso()
            missing_message = (
                "文字起こし実行ファイルが見つかりません: "
                f"{TRANSCRIPTION_EXECUTABLE_PATH}"
            )
            self._publish_status(
                state="error",
                process_alive=False,
                session=current_session,
                last_error_at=missing_at,
                last_error_message=missing_message,
                event_name="実行ファイル未検出",
                event_detail=missing_message,
                event_time=missing_at,
            )
            return

        try:
            process = _start_transcription_process()
        except OSError as exc:
            failed_at = _now_iso()
            self._publish_status(
                state="error",
                process_alive=False,
                session=current_session,
                last_error_at=failed_at,
                last_error_message=str(exc),
                event_name="起動失敗",
                event_detail=f"文字起こしプロセスの起動に失敗しました: {exc}",
                event_time=failed_at,
            )
            return

        with self._lock:
            self._process = process

        started_at = _now_iso()
        self._publish_status(
            state="idle",
            process_alive=True,
            session=current_session,
            event_name="起動成功",
            event_detail="文字起こしプロセスが起動しました。",
            event_time=started_at,
        )
        self._publish_status(
            state="idle",
            process_alive=True,
            session=current_session,
            event_name="待機中",
            event_detail="音声入力を待機しています。",
            event_time=started_at,
        )

        exit_code: int | None = None
        csv_sync_thread = threading.Thread(
            target=self._run_csv_sync,
            args=(process,),
            daemon=True,
        )
        csv_sync_thread.start()

        try:
            while not self._stop_event.is_set():
                polled_exit_code = process.poll()
                if polled_exit_code is not None:
                    exit_code = polled_exit_code
                    break
                self._stop_event.wait(0.5)
            if exit_code is None and not self._stop_event.is_set():
                exit_code = process.poll()
        except Exception as exc:
            if not self._stop_event.is_set():
                failed_at = _now_iso()
                self._publish_status(
                    state="error",
                    process_alive=False,
                    session=self._current_session(),
                    last_error_at=failed_at,
                    last_error_message=str(exc),
                    event_name="プロセス異常終了",
                    event_detail=f"文字起こしプロセスが異常終了しました: {exc}",
                    event_time=failed_at,
                )
        finally:
            csv_sync_thread.join(timeout=2.0)
            _terminate_process(process)
            with self._lock:
                if self._process is process:
                    self._process = None
            if exit_code is not None and not self._stop_event.is_set():
                finished_at = _now_iso()
                if exit_code == 0:
                    self._publish_status(
                        state="stopped",
                        process_alive=False,
                        session=self._current_session(),
                        last_error_at=None,
                        last_error_message=None,
                        event_name="停止",
                        event_detail="文字起こしプロセスが正常終了しました。",
                        event_time=finished_at,
                    )
                else:
                    detail = (
                        f"文字起こしプロセスが終了コード {exit_code} で停止しました。"
                    )
                    self._publish_status(
                        state="error",
                        process_alive=False,
                        session=self._current_session(),
                        last_error_at=finished_at,
                        last_error_message=detail,
                        event_name="プロセス異常終了",
                        event_detail=detail,
                        event_time=finished_at,
                    )

    def _run_csv_sync(self, process: subprocess.Popen[str]) -> None:
        processed_row_count = _read_transcript_row_count()
        pending_rows: deque[tuple[str, str]] = deque()

        while not self._stop_event.is_set():
            current_session = self._current_session()
            new_rows, processed_row_count = _read_new_transcript_rows(
                processed_row_count,
                current_session,
            )
            pending_rows.extend(new_rows)
            self._flush_pending_rows(pending_rows)

            if process.poll() is not None:
                final_session = self._current_session()
                final_rows, processed_row_count = _read_new_transcript_rows(
                    processed_row_count,
                    final_session,
                )
                pending_rows.extend(final_rows)
                self._flush_pending_rows(pending_rows)
                return

            if self._stop_event.wait(0.5):
                return

    def _flush_pending_rows(self, pending_rows: deque[tuple[str, str]]) -> None:
        while pending_rows and not self._stop_event.is_set():
            session, text = pending_rows[0]
            try:
                item = post_transcription(session, text)
            except Exception as exc:
                failed_at = _now_iso()
                self._publish_status(
                    state="error",
                    process_alive=True,
                    session=session,
                    last_error_at=failed_at,
                    last_error_message=str(exc),
                    event_name="送信失敗",
                    event_detail=f"文字起こしの保存に失敗しました: {exc}",
                    event_time=failed_at,
                )
                return

            pending_rows.popleft()
            created_at = str(item.get("created_at") or _now_iso())
            self._publish_status(
                state="running",
                process_alive=True,
                session=session,
                last_success_at=created_at,
                event_name="送信成功",
                event_detail="文字起こしをバックエンドへ保存しました。",
                event_time=created_at,
            )
            self._notify_item(item)

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


def _terminate_process(process: subprocess.Popen[str]) -> None:
    stdin_stream = process.stdin
    if stdin_stream is not None:
        try:
            stdin_stream.close()
        except Exception:
            pass
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


def _read_transcript_row_count() -> int:
    return len(_read_transcript_text_rows())


def _read_new_transcript_rows(
    processed_row_count: int,
    session: str | None,
) -> tuple[list[tuple[str, str]], int]:
    rows = _read_transcript_text_rows()
    row_count = len(rows)
    if row_count < processed_row_count:
        processed_row_count = row_count

    if session is None:
        return [], row_count

    new_rows = [
        (session, text)
        for text in rows[processed_row_count:]
        if text
    ]
    return new_rows, row_count


def _read_transcript_text_rows() -> list[str]:
    path = TRANSCRIPTION_CSV_PATH
    if not path.is_file():
        return []

    texts: list[str] = []
    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            errors="replace",
            newline="",
        ) as handle:
            reader = csv.reader(handle)
            for row in reader:
                text = _text_from_transcript_row(row)
                if text is not None:
                    texts.append(text)
    except OSError:
        return []

    return texts


def _text_from_transcript_row(row: list[str]) -> str | None:
    if len(row) < 2:
        return None

    spaced_text = row[1].strip()
    normalized_text = row[2].strip() if len(row) >= 3 else ""
    text = normalized_text or spaced_text
    if not text:
        return None
    return text


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
