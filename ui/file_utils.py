from __future__ import annotations

_WINDOWS_RESERVED_FILENAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)
_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')


def sanitize_filename_component(value: str) -> str:
    sanitized = "".join(
        "_" if (character in _INVALID_FILENAME_CHARS or ord(character) < 32) else character
        for character in value.strip()
    ).strip(" .")
    if not sanitized:
        return "default"
    if sanitized.upper() in _WINDOWS_RESERVED_FILENAMES:
        return f"{sanitized}_"
    return sanitized


def build_export_filename(session_name: str | None, extension: str) -> str:
    safe_session_name = sanitize_filename_component((session_name or "").strip() or "default")
    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return f"{safe_session_name}{normalized_extension}"
