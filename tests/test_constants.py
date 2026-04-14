from __future__ import annotations

import unittest
from pathlib import Path

from config import constants


class ConstantsPathTests(unittest.TestCase):
    def test_transcription_temp_dir_resolves_from_project_root_in_source_mode(self) -> None:
        project_root = Path(__file__).resolve().parent.parent

        self.assertEqual(Path(constants.BASE_DIR), project_root)
        self.assertEqual(
            constants.TRANSCRIPTION_TEMP_DIR,
            project_root / "transcription-temp",
        )


if __name__ == "__main__":
    unittest.main()
