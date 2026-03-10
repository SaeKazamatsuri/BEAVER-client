import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def _candidate_base_dir_paths() -> tuple[Path, ...]:
    candidates: list[Path] = []

    bundle_dir = getattr(sys, "_MEIPASS", None)
    if isinstance(bundle_dir, str) and bundle_dir:
        candidates.append(Path(bundle_dir))

    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)

    candidates.append(Path(__file__).resolve().parent.parent)

    unique_candidates: list[Path] = []
    for candidate in candidates:
        if candidate not in unique_candidates:
            unique_candidates.append(candidate)
    return tuple(unique_candidates)


def _resolve_base_dir() -> Path:
    return _candidate_base_dir_paths()[0]


def _resolve_transcription_work_dir() -> Path:
    for base_dir in _candidate_base_dir_paths():
        transcription_dir = base_dir / "transcription"
        if transcription_dir.is_dir():
            return transcription_dir
    return _resolve_base_dir() / "transcription"


_BASE_DIR_PATH = _resolve_base_dir()
BASE_DIR = str(_BASE_DIR_PATH)
DEFAULT_PUBLIC_BACKEND_BASE_URL = "https://api.beaver.works"


def _trim_trailing_slash(value: str) -> str:
    return value.rstrip("/")


def _derive_ws_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    ws_path = "/ws" if not path else f"{path}/ws"
    return urlunsplit((scheme, parsed.netloc, ws_path, "", ""))


BACKEND_BASE_URL = _trim_trailing_slash(
    os.environ.get("BACKEND_BASE_URL")
    or os.environ.get("RELAY_SERVER_URL")
    or DEFAULT_PUBLIC_BACKEND_BASE_URL
)
BACKEND_WS_BASE_URL = _trim_trailing_slash(
    os.environ.get("BACKEND_WS_BASE_URL") or _derive_ws_base_url(BACKEND_BASE_URL)
)
BACKEND_WS_ORIGIN = os.environ.get("BACKEND_WS_ORIGIN", "https://beaver.works")
BACKEND_HTTP_TIMEOUT_SEC = 10

TRANSCRIPTION_WORK_DIR = _resolve_transcription_work_dir()
TRANSCRIPTION_CSV_PATH = TRANSCRIPTION_WORK_DIR / "transcript.csv"
TRANSCRIPTION_EXECUTABLE_PATH = TRANSCRIPTION_WORK_DIR / "vosk.exe"

STAMP_BALLOON_LIFETIME_SEC = 8.0
STAMP_BALLOON_MIN_SPEED_PX = 90.0
STAMP_BALLOON_MAX_SPEED_PX = 200.0
STAMP_BALLOON_MAX_ACTIVE = 8
STAMP_BALLOON_MAX_WIDTH = 220
STAMP_BALLOON_START_PADDING = 40
STAMP_BALLOON_WOBBLE_AMPLITUDE = 25.0
STAMP_BALLOON_WOBBLE_FREQ_MIN = 0.6
STAMP_BALLOON_WOBBLE_FREQ_MAX = 1.2
STAMP_RECENT_WINDOW_SEC = 20.0
STAMP_DOWNLOAD_TIMEOUT = 10
OVERLAY_TRANSPARENT_COLOR = "#00ff00"
STAMP_ID_CACHE_SIZE = 128
