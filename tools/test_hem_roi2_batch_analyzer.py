import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "resource" / "pywrapper"))
import api_server

from tools import hem_roi2_batch_analyzer as analyzer


def write_frame(path: Path, value: int, size=(20, 20)) -> None:
    arr = np.full((size[1], size[0], 3), value, dtype=np.uint8)
    Image.fromarray(arr).save(path)


class HemRoi2BatchAnalyzerTests(unittest.TestCase):
    def test_analyze_sequence_uses_current_roi2_rect_and_returns_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "114806_20260614_000000_862"
            seq.mkdir()
            write_frame(seq / "00001_2026-06-14_00-00-00.000_frame.png", 10)
            write_frame(seq / "00002_2026-06-14_00-00-00.070_frame.png", 20)
            write_frame(seq / "00003_2026-06-14_00-00-00.140_frame.png", 12)

            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=None,
                settings_path=None,
                focus_point="PointF(10, 10)",
                focus_points_csv=None,
                provider_depth_mm=100.0,
                focus_y_offset_mm=0.0,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
                before_frame_index=1,
                after_strategy="roi2_peak",
                include_selected_debug=False,
                max_sequences=None,
            )

            row, frames = analyzer.analyze_sequence(seq, cfg, {})

            expected_rect = api_server.compute_roi_region(
                (20, 20),
                (10, 10),
                {"left": 2, "right": 2, "top": 3, "bottom": 3},
            )
            self.assertEqual(row["focus_anchor"], "10,10")
            self.assertEqual(row["offset_anchor"], "10,10")
            self.assertEqual(row["roi2_rect"], ",".join(str(v) for v in expected_rect))
            self.assertEqual(row["before_mean"], "10.000000")
            self.assertEqual(row["after_mean"], "20.000000")
            self.assertEqual(row["roi2_diff"], "10.000000")
            self.assertEqual(row["roi2_color"], "green")
            self.assertEqual(row["after_frame_index"], "2")
            self.assertEqual(len(frames), 3)

    def test_write_outputs_creates_summary_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "seq"
            seq.mkdir()
            write_frame(seq / "00001_2026-06-14_00-00-00.000_frame.png", 10)
            write_frame(seq / "00002_2026-06-14_00-00-00.070_frame.png", 18)
            write_frame(seq / "after_roi2.png", 255, size=(4, 4))
            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=root / "frames.csv",
                settings_path=None,
                focus_point=[10, 10],
                focus_points_csv=None,
                provider_depth_mm=100.0,
                focus_y_offset_mm=0.0,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
                before_frame_index=1,
                after_strategy="last",
                include_selected_debug=False,
                max_sequences=None,
            )

            rows = analyzer.analyze_root(cfg)

            self.assertEqual(len(rows), 1)
            with cfg.output_csv.open("r", encoding="utf-8-sig", newline="") as f:
                saved = list(csv.DictReader(f))
            self.assertEqual(saved[0]["sequence"], "seq")
            self.assertEqual(saved[0]["frame_count"], "2")
            self.assertEqual(saved[0]["roi2_color"], "green")
            self.assertTrue(cfg.per_frame_csv.exists())

    def test_missing_focus_point_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "seq"
            seq.mkdir()
            write_frame(seq / "00001_2026-06-14_00-00-00.000_frame.png", 10)
            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=None,
                settings_path=None,
                focus_point=None,
                focus_points_csv=None,
                provider_depth_mm=100.0,
                focus_y_offset_mm=0.0,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
                before_frame_index=1,
                after_strategy="last",
                include_selected_debug=False,
                max_sequences=None,
            )

            with self.assertRaisesRegex(ValueError, "focus_point is required"):
                analyzer.analyze_sequence(seq, cfg, {})

    def test_focus_y_offset_requires_depth(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "seq"
            seq.mkdir()
            write_frame(seq / "00001_2026-06-14_00-00-00.000_frame.png", 10, size=(200, 200))
            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=None,
                settings_path=None,
                focus_point="PointF(100, 100)",
                focus_points_csv=None,
                provider_depth_mm=None,
                focus_y_offset_mm=2.5,
                roi2_extension_params={"left": 5, "right": 5, "top": 6, "bottom": 6},
                difference_threshold=5.0,
                before_frame_index=1,
                after_strategy="last",
                include_selected_debug=False,
                max_sequences=None,
            )

            with self.assertRaisesRegex(ValueError, "provider ultrasound depth is required"):
                analyzer.analyze_sequence(seq, cfg, {})


if __name__ == "__main__":
    unittest.main()
