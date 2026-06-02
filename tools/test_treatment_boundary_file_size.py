import json
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).with_name("treatment_boundary_file_size.py")


def write_placeholder_png(path, byte_count):
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + (b"x" * (byte_count - 8)))


class TreatmentBoundaryFileSizeTest(unittest.TestCase):
    def test_cli_outputs_boundary_frames_for_single_active_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_placeholder_png(folder / "00001_sample_before.png", 20)
            write_placeholder_png(folder / "00002_sample_frame.png", 20)
            write_placeholder_png(folder / "00003_sample_frame.png", 80)
            write_placeholder_png(folder / "00004_sample_frame.png", 80)
            write_placeholder_png(folder / "00005_sample_frame.png", 20)
            write_placeholder_png(folder / "00006_sample_roi_frame.png", 20)
            write_placeholder_png(folder / "00003_sample_frame_roi.png", 200)
            write_placeholder_png(folder / "00004_sample_after_peak.png", 200)

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--folder",
                    str(folder),
                    "--baseline-count",
                    "2",
                    "--size-ratio-threshold",
                    "1.5",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["method"], "file_size")
            self.assertEqual(payload["folder"], str(folder.resolve()))
            self.assertEqual(payload["frame_count"], 6)
            self.assertEqual(payload["before_frame"], "00002_sample_frame.png")
            self.assertEqual(payload["active_start_frame"], "00003_sample_frame.png")
            self.assertEqual(payload["active_end_frame"], "00004_sample_frame.png")
            self.assertEqual(payload["after_frame"], "00005_sample_frame.png")
            self.assertEqual(payload["baseline_size"], 20)
            self.assertEqual(payload["size_ratio_threshold"], 1.5)

    def test_analyze_folder_fails_when_no_large_file_interval_exists(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from treatment_boundary_file_size import (  # pylint: disable=import-outside-toplevel
            BoundaryDetectionError,
            analyze_folder,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_placeholder_png(folder / "00001_sample_before.png", 20)
            write_placeholder_png(folder / "00002_sample_frame.png", 20)
            write_placeholder_png(folder / "00003_sample_frame.png", 21)
            write_placeholder_png(folder / "00004_sample_frame.png", 21)
            write_placeholder_png(folder / "00005_sample_frame.png", 20)

            with self.assertRaises(BoundaryDetectionError):
                analyze_folder(folder, baseline_count=2)

    def test_analyze_folder_fails_when_baseline_frame_count_is_missing(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from treatment_boundary_file_size import (  # pylint: disable=import-outside-toplevel
            BoundaryDetectionError,
            analyze_folder,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            write_placeholder_png(folder / "00001_sample_before.png", 20)
            write_placeholder_png(folder / "00002_sample_frame.png", 20)
            write_placeholder_png(folder / "00003_sample_frame.png", 80)

            with self.assertRaisesRegex(
                BoundaryDetectionError, "need at least 6 frames for baseline"
            ):
                analyze_folder(folder)

    def test_main_returns_nonzero_json_when_folder_selection_is_cancelled(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import treatment_boundary_file_size  # pylint: disable=import-outside-toplevel

        stderr = io.StringIO()
        with mock.patch.object(
            treatment_boundary_file_size,
            "choose_folder_with_dialog",
            side_effect=treatment_boundary_file_size.BoundaryDetectionError(
                "folder selection was cancelled"
            ),
        ), redirect_stderr(stderr):
            exit_code = treatment_boundary_file_size.main([])

        self.assertEqual(exit_code, 1)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["method"], "file_size")
        self.assertEqual(payload["error"], "folder selection was cancelled")


if __name__ == "__main__":
    unittest.main()
