from pathlib import Path
import unittest

from gentrace import __version__


class VersionTests(unittest.TestCase):
    def test_version_file_matches_package(self):
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
        self.assertEqual(version_file.read_text(encoding="utf-8").strip(), __version__)


if __name__ == "__main__":
    unittest.main()
