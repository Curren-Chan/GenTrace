from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from gentrace.records import (
    IMAGE_MISSING,
    IMAGE_PRESENT,
    IMAGE_UNKNOWN,
    absolute_image_path,
    image_status,
)


class ImageReferenceTests(unittest.TestCase):
    def test_unknown_when_legacy_job_has_no_recorded_path(self) -> None:
        summary = image_status([])
        self.assertEqual(summary.state, IMAGE_UNKNOWN)
        self.assertEqual(summary.display, "Unknown")

    def test_present_then_missing_without_changing_the_generation_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "generated.png"
            path.write_bytes(b"png")
            self.assertEqual(image_status([path]).state, IMAGE_PRESENT)
            path.unlink()
            summary = image_status([path])
            self.assertEqual(summary.state, IMAGE_MISSING)
            self.assertEqual(summary.total, 1)
            self.assertEqual(summary.present, 0)

    def test_partial_multi_output_is_missing_but_keeps_an_openable_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            present = Path(temporary) / "present.png"
            missing = Path(temporary) / "missing.png"
            present.write_bytes(b"png")
            summary = image_status([present, missing])
            self.assertEqual(summary.state, IMAGE_MISSING)
            self.assertEqual(summary.first_present, present)
            self.assertEqual(summary.display, "Missing (1/2)")

    def test_stored_image_path_is_absolute(self) -> None:
        path = absolute_image_path(Path("relative") / "generated.png")
        self.assertTrue(path.is_absolute())
        self.assertEqual(path, Path(os.path.abspath(Path("relative") / "generated.png")))


if __name__ == "__main__":
    unittest.main()
