import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT_PATH = Path(__file__).with_name("treatment_boundary_roi1_threshold.py")


def write_rgba(path, value, alpha=255):
    image = Image.new("RGBA", (6, 4), (value, value, value, alpha))
    image.save(path)


class TreatmentBoundaryRoi1ThresholdTest(unittest.TestCase):
    def test_cli_outputs_boundary_frames_for_low_low_high_high_low_sequence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_rgba(folder / "00001_case_before.png", 10)
            write_rgba(folder / "00002_case_frame.png", 10)
            write_rgba(folder / "00003_case_frame.png", 40, alpha=0)
            write_rgba(folder / "00004_case_frame.png", 40, alpha=0)
            write_rgba(folder / "00005_case_frame.png", 10)
            write_rgba(folder / "00003_case_frame_roi.png", 255)
            write_rgba(folder / "00006_case_after.png", 255)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--folder",
                    str(folder),
                    "--baseline-count",
                    "2",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["method"], "roi1_full_frame_gray_threshold")
            self.assertEqual(payload["folder"], str(folder.resolve()))
            self.assertEqual(payload["before_frame"], "00002_case_frame.png")
            self.assertEqual(payload["active_start_frame"], "00003_case_frame.png")
            self.assertEqual(payload["active_end_frame"], "00004_case_frame.png")
            self.assertEqual(payload["after_frame"], "00005_case_frame.png")
            self.assertEqual(payload["frame_count"], 5)

    def test_analyze_folder_fails_when_no_active_interval_exists(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from treatment_boundary_roi1_threshold import (  # pylint: disable=import-outside-toplevel
            BoundaryDetectionError,
            analyze_folder,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_rgba(folder / "00001_case_before.png", 10)
            write_rgba(folder / "00002_case_frame.png", 10)
            write_rgba(folder / "00003_case_frame.png", 10)
            write_rgba(folder / "00004_case_frame.png", 10)
            write_rgba(folder / "00005_case_frame.png", 10)

            with self.assertRaises(BoundaryDetectionError):
                analyze_folder(folder, baseline_count=2)


if __name__ == "__main__":
    unittest.main()
