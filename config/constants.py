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


def _resolve_transcription_temp_dir() -> Path:
    return _resolve_base_dir() / "transcription-temp"


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


def _derive_client_ws_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/")
    ws_path = "/client/ws" if not path else f"{path}/client/ws"
    return urlunsplit((scheme, parsed.netloc, ws_path, "", ""))


def _derive_transcription_ws_base_url(ws_base_url: str) -> str:
    parsed = urlsplit(ws_base_url)
    path = parsed.path.rstrip("/")
    transcription_path = "/ws/transcription" if not path else f"{path}/transcription"
    return urlunsplit((parsed.scheme, parsed.netloc, transcription_path, "", ""))


BACKEND_BASE_URL = _trim_trailing_slash(
    os.environ.get("BACKEND_BASE_URL")
    or os.environ.get("RELAY_SERVER_URL")
    or DEFAULT_PUBLIC_BACKEND_BASE_URL
)
BACKEND_WS_BASE_URL = _trim_trailing_slash(
    os.environ.get("BACKEND_WS_BASE_URL") or _derive_ws_base_url(BACKEND_BASE_URL)
)
BACKEND_CLIENT_WS_BASE_URL = _trim_trailing_slash(
    os.environ.get("BACKEND_CLIENT_WS_BASE_URL")
    or _derive_client_ws_base_url(BACKEND_BASE_URL)
)
BACKEND_TRANSCRIPTION_WS_BASE_URL = _trim_trailing_slash(
    os.environ.get("BACKEND_TRANSCRIPTION_WS_BASE_URL")
    or _derive_transcription_ws_base_url(BACKEND_WS_BASE_URL)
)
BACKEND_WS_ORIGIN = os.environ.get("BACKEND_WS_ORIGIN", "https://beaver.works")
BACKEND_HTTP_TIMEOUT_SEC = 10
BACKEND_UPLOAD_TIMEOUT_SEC = 120

TRANSCRIPTION_TEMP_DIR = _resolve_transcription_temp_dir()
TRANSCRIPTION_SAMPLE_RATE_HZ = 16_000
TRANSCRIPTION_CHANNELS = 1
TRANSCRIPTION_SAMPLE_WIDTH_BYTES = 2
TRANSCRIPTION_CHUNK_DURATION_SEC = 180
TRANSCRIPTION_READ_FRAMES = 1_600
TRANSCRIPTION_BACKLOG_LIMIT = 10
TRANSCRIPTION_WS_PART_SIZE_BYTES = 64 * 1024
TRANSCRIPTION_GAIN_TARGET_RMS = 0.2
TRANSCRIPTION_GAIN_MAX = 12.0
TRANSCRIPTION_GAIN_SMOOTHING = 0.05
TRANSCRIPTION_GAIN_NOISE_FLOOR = 0.005

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
