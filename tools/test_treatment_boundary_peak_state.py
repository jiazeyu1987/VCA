import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT = Path(__file__).with_name("treatment_boundary_peak_state.py")


def write_rgb(path, value):
    image = Image.new("RGB", (4, 3), (value, value, value))
    image.save(path)


class TreatmentBoundaryPeakStateTest(unittest.TestCase):
    def run_script(self, folder):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--folder", str(folder)],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_low_low_high_high_low_finds_before_after_boundaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_rgb(folder / "00001_case_before.png", 10)
            write_rgb(folder / "00002_case_frame.png", 12)
            write_rgb(folder / "00003_case_frame.png", 40)
            write_rgb(folder / "00004_case_frame.png", 50)
            write_rgb(folder / "00005_case_frame.png", 12)
            write_rgb(folder / "00006_case_after.png", 200)

            completed = self.run_script(folder)

            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["method"], "peak_state")
            self.assertEqual(result["folder"], str(folder.resolve()))
            self.assertEqual(result["before_frame"], "00002_case_frame.png")
            self.assertEqual(result["active_start_frame"], "00003_case_frame.png")
            self.assertEqual(result["active_end_frame"], "00004_case_frame.png")
            self.assertEqual(result["after_frame"], "00005_case_frame.png")
            self.assertEqual(result["frame_count"], 5)
            self.assertEqual(result["high_threshold"], 35.0)
            self.assertEqual(result["end_diff_threshold"], 7.0)

    def test_fails_when_active_state_never_returns_to_baseline(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_rgb(folder / "00001_case_before.png", 10)
            write_rgb(folder / "00002_case_frame.png", 11)
            write_rgb(folder / "00003_case_frame.png", 40)
            write_rgb(folder / "00004_case_frame.png", 42)

            completed = self.run_script(folder)

            self.assertNotEqual(completed.returncode, 0)
            self.assertEqual(completed.stdout, "")
            self.assertIn("after_frame", completed.stderr)


if __name__ == "__main__":
    unittest.main()
