import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT_PATH = Path(__file__).with_name("treatment_boundary_roi23_threshold.py")


def write_rgba(path, roi2_value, roi3_value, background_value=3, alpha=255):
    image = Image.new("RGBA", (8, 6), (background_value, background_value, background_value, alpha))
    pixels = image.load()
    for y in range(1, 3):
        for x in range(1, 4):
            pixels[x, y] = (roi2_value, roi2_value, roi2_value, alpha)
    for y in range(3, 5):
        for x in range(4, 7):
            pixels[x, y] = (roi3_value, roi3_value, roi3_value, alpha)
    image.save(path)


def write_meta(folder):
    (folder / "meta.json").write_text(
        json.dumps({"roi2_rect": [1, 1, 4, 3], "roi3_rect": [4, 3, 7, 5]}),
        encoding="utf-8",
    )


class TreatmentBoundaryRoi23ThresholdTest(unittest.TestCase):
    def test_cli_outputs_boundary_frames_for_low_low_high_high_low_sequence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_meta(folder)
            write_rgba(folder / "00001_case_before.png", 10, 10)
            write_rgba(folder / "00002_case_frame.png", 10, 10)
            write_rgba(folder / "00003_case_frame.png", 40, 40, alpha=0)
            write_rgba(folder / "00004_case_frame.png", 40, 40, alpha=0)
            write_rgba(folder / "00005_case_frame.png", 10, 10)
            write_rgba(folder / "00003_case_frame_roi.png", 255, 255)
            write_rgba(folder / "00006_case_after.png", 255, 255)

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
            self.assertEqual(payload["method"], "roi23_gray_threshold")
            self.assertEqual(payload["folder"], str(folder.resolve()))
            self.assertEqual(payload["before_frame"], "00002_case_frame.png")
            self.assertEqual(payload["active_start_frame"], "00003_case_frame.png")
            self.assertEqual(payload["active_end_frame"], "00004_case_frame.png")
            self.assertEqual(payload["after_frame"], "00005_case_frame.png")
            self.assertEqual(payload["frame_count"], 5)
            self.assertEqual(payload["roi2_rect"], [1, 1, 4, 3])
            self.assertEqual(payload["roi3_rect"], [4, 3, 7, 5])

    def test_cli_fails_when_meta_json_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_rgba(folder / "00001_case_before.png", 10, 10)
            write_rgba(folder / "00002_case_frame.png", 10, 10)
            write_rgba(folder / "00003_case_frame.png", 40, 40)
            write_rgba(folder / "00004_case_frame.png", 40, 40)
            write_rgba(folder / "00005_case_frame.png", 10, 10)

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

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("error: meta.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
