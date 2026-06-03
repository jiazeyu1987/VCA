import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SCRIPT_PATH = Path(__file__).with_name("treatment_boundary_bright_ratio.py")


def write_png(path, value, bright_pixels=0):
    image = Image.new("RGB", (10, 10), (value, value, value))
    if bright_pixels:
        pixels = image.load()
        for index in range(bright_pixels):
            x = index % 10
            y = index // 10
            pixels[x, y] = (255, 255, 255)
    image.save(path)


class TreatmentBoundaryBrightRatioTest(unittest.TestCase):
    def test_cli_outputs_boundary_frames_for_single_active_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_png(folder / "00001_sample_before.png", 10)
            write_png(folder / "00002_sample_frame.png", 10)
            write_png(folder / "00003_sample_frame.png", 255)
            write_png(folder / "00004_sample_frame.png", 255)
            write_png(folder / "00005_sample_frame.png", 10)

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
            self.assertEqual(payload["method"], "bright_ratio")
            self.assertEqual(payload["folder"], str(folder.resolve()))
            self.assertEqual(payload["frame_count"], 5)
            self.assertEqual(payload["before_frame"], "00002_sample_frame.png")
            self.assertEqual(payload["active_start_frame"], "00003_sample_frame.png")
            self.assertEqual(payload["active_end_frame"], "00004_sample_frame.png")
            self.assertEqual(payload["after_frame"], "00005_sample_frame.png")
            self.assertEqual(payload["bright_threshold"], 35.0)
            self.assertEqual(payload["active_ratio_threshold"], 0.20)

    def test_analyze_folder_fails_when_bright_ratio_is_insufficient(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from treatment_boundary_bright_ratio import (  # pylint: disable=import-outside-toplevel
            BoundaryDetectionError,
            analyze_folder,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_png(folder / "00001_sample_before.png", 10)
            write_png(folder / "00002_sample_frame.png", 10)
            write_png(folder / "00003_sample_frame.png", 10, bright_pixels=4)
            write_png(folder / "00004_sample_frame.png", 10, bright_pixels=4)
            write_png(folder / "00005_sample_frame.png", 10)

            with self.assertRaises(BoundaryDetectionError):
                analyze_folder(folder, baseline_count=2)

    def test_low_frames_with_small_bright_regions_do_not_start_active_interval(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from treatment_boundary_bright_ratio import analyze_folder  # pylint: disable=import-outside-toplevel

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_png(folder / "00001_sample_before.png", 10, bright_pixels=6)
            write_png(folder / "00002_sample_frame.png", 10, bright_pixels=6)
            write_png(folder / "00003_sample_frame.png", 10, bright_pixels=30)
            write_png(folder / "00004_sample_frame.png", 10, bright_pixels=30)
            write_png(folder / "00005_sample_frame.png", 10, bright_pixels=6)

            payload = analyze_folder(folder, baseline_count=2)

            self.assertEqual(payload["before_frame"], "00002_sample_frame.png")
            self.assertEqual(payload["active_start_frame"], "00003_sample_frame.png")
            self.assertEqual(payload["active_end_frame"], "00004_sample_frame.png")
            self.assertEqual(payload["after_frame"], "00005_sample_frame.png")


if __name__ == "__main__":
    unittest.main()
