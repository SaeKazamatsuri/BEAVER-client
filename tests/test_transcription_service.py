from __future__ import annotations

import subprocess
import sys
import types
import unittest
from unittest.mock import patch

backend_api_stub = types.ModuleType("services.backend_api")


def _post_transcription_stub(session: str, text: str) -> dict[str, object]:
    return {"session": session, "text": text}


backend_api_stub.post_transcription = _post_transcription_stub

with patch.dict(sys.modules, {"services.backend_api": backend_api_stub}):
    from services import transcription_service
    from services.transcription_service import (
        _build_hidden_process_options,
        _start_transcription_process,
    )


class HiddenProcessOptionsTests(unittest.TestCase):
    def test_build_hidden_process_options_matches_platform(self) -> None:
        startupinfo, creationflags = _build_hidden_process_options()

        if sys.platform != "win32":
            self.assertIsNone(startupinfo)
            self.assertEqual(creationflags, 0)
            return

        self.assertIsNotNone(startupinfo)
        assert startupinfo is not None
        self.assertEqual(creationflags, subprocess.CREATE_NO_WINDOW)
        self.assertEqual(startupinfo.wShowWindow, subprocess.SW_HIDE)
        self.assertNotEqual(
            startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW,
            0,
        )

    def test_start_transcription_process_sets_hidden_window_options(self) -> None:
        with patch.object(transcription_service.subprocess, "Popen") as popen_mock:
            _start_transcription_process()

        kwargs = popen_mock.call_args.kwargs

        if sys.platform != "win32":
            self.assertNotIn("startupinfo", kwargs)
            self.assertNotIn("creationflags", kwargs)
            return

        self.assertIn("startupinfo", kwargs)
        self.assertEqual(kwargs.get("creationflags"), subprocess.CREATE_NO_WINDOW)

        startupinfo = kwargs.get("startupinfo")
        self.assertIsNotNone(startupinfo)
        assert startupinfo is not None
        self.assertEqual(startupinfo.wShowWindow, subprocess.SW_HIDE)
        self.assertNotEqual(
            startupinfo.dwFlags & subprocess.STARTF_USESHOWWINDOW,
            0,
        )


if __name__ == "__main__":
    unittest.main()
