from __future__ import annotations

import unittest
from pathlib import Path

from config import constants


class ConstantsPathTests(unittest.TestCase):
    def test_transcription_paths_resolve_from_project_root_in_source_mode(self) -> None:
        project_root = Path(__file__).resolve().parent.parent

        self.assertEqual(Path(constants.BASE_DIR), project_root)
        self.assertEqual(
            constants.TRANSCRIPTION_WORK_DIR,
            project_root / "transcription",
        )
        self.assertEqual(
            constants.TRANSCRIPTION_EXECUTABLE_PATH,
            project_root / "transcription" / "vosk.exe",
        )


if __name__ == "__main__":
    unittest.main()
