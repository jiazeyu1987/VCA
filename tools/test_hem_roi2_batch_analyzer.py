import csv
import sys
import tempfile
import threading
import time
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
    def test_default_focus_point_matches_current_algorithm_focus(self):
        self.assertEqual(
            analyzer.DEFAULT_FOCUS_POINT,
            "PointF(299.2863464355469, 285.9410705566406)",
        )
        self.assertEqual(
            analyzer._parse_focus_point_value(analyzer.DEFAULT_FOCUS_POINT),
            (299, 285),
        )

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

    def test_render_sequence_preview_draws_roi2_and_focus_toggles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "seq"
            seq.mkdir()
            frame = seq / "00001_2026-06-14_00-00-00.000_frame.png"
            write_frame(frame, 10, size=(200, 200))
            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=None,
                settings_path=None,
                focus_point="PointF(100, 100)",
                focus_points_csv=None,
                provider_depth_mm=100.0,
                focus_y_offset_mm=0.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=5.0,
                before_frame_index=1,
                after_strategy="last",
                include_selected_debug=False,
                max_sequences=None,
            )

            hidden, hidden_meta = analyzer.render_sequence_preview_image(
                frame,
                seq.name,
                cfg,
                {},
                False,
                False,
                max_size=(200, 200),
            )
            visible, visible_meta = analyzer.render_sequence_preview_image(
                frame,
                seq.name,
                cfg,
                {},
                True,
                True,
                max_size=(200, 200),
            )

            self.assertEqual(hidden_meta["focus_anchor"], (100, 100))
            self.assertEqual(hidden_meta["roi2_rect"], (95, 95, 105, 105))
            self.assertEqual(visible_meta["roi2_rect"], hidden_meta["roi2_rect"])
            self.assertNotEqual(visible.getpixel((95, 95)), hidden.getpixel((95, 95)))
            self.assertNotEqual(visible.getpixel((100, 100)), hidden.getpixel((100, 100)))

    def test_render_sequence_preview_scales_up_to_available_area(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "seq"
            seq.mkdir()
            frame = seq / "00001_2026-06-14_00-00-00.000_frame.png"
            write_frame(frame, 10, size=(200, 100))
            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=None,
                settings_path=None,
                focus_point="PointF(100, 50)",
                focus_points_csv=None,
                provider_depth_mm=100.0,
                focus_y_offset_mm=0.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=5.0,
                before_frame_index=1,
                after_strategy="last",
                include_selected_debug=False,
                max_sequences=None,
            )

            image, meta = analyzer.render_sequence_preview_image(
                frame,
                seq.name,
                cfg,
                {},
                False,
                False,
                max_size=(800, 600),
            )

            self.assertEqual(image.size, (800, 400))
            self.assertEqual(meta["scale"], 4.0)

    def test_gui_state_builds_analyzer_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "summary.csv"
            frames = root / "frames.csv"
            settings = root / "settings.json"
            settings.write_text(
                '{"focus_guides":{"y_offset_mm":0},"peak_detect":{"difference_threshold":0.5,'
                '"roi2_extension_params":{"left":40,"right":40,"top":50,"bottom":30}}}',
                encoding="utf-8",
            )
            state = analyzer.GuiState(
                root_dir=str(root),
                output_csv=str(output),
                per_frame_csv=str(frames),
                settings_path=str(settings),
                focus_point="PointF(300, 256)",
                focus_points_csv="",
                provider_depth_mm="100",
                focus_y_offset_mm="0",
                roi2_left="10",
                roi2_right="11",
                roi2_top="12",
                roi2_bottom="13",
                difference_threshold="2.5",
                before_frame_index="1",
                after_strategy="last",
                include_selected_debug=False,
                max_sequences="5",
            )

            cfg = analyzer.config_from_gui_state(state)

            self.assertEqual(cfg.root_dir, root)
            self.assertEqual(cfg.output_csv, output)
            self.assertEqual(cfg.per_frame_csv, frames)
            self.assertEqual(cfg.focus_point, "PointF(300, 256)")
            self.assertEqual(cfg.provider_depth_mm, 100.0)
            self.assertEqual(cfg.roi2_extension_params, {"left": 10, "right": 11, "top": 12, "bottom": 13})
            self.assertEqual(cfg.difference_threshold, 2.5)
            self.assertEqual(cfg.after_strategy, "last")
            self.assertEqual(cfg.max_sequences, 5)

    def test_gui_state_maps_chinese_after_strategy_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = analyzer.GuiState(
                root_dir=str(root),
                output_csv=str(root / "summary.csv"),
                per_frame_csv="",
                settings_path="",
                focus_point=analyzer.DEFAULT_FOCUS_POINT,
                focus_points_csv="",
                provider_depth_mm="100",
                focus_y_offset_mm="0",
                roi2_left="40",
                roi2_right="40",
                roi2_top="50",
                roi2_bottom="30",
                difference_threshold="0.5",
                before_frame_index="1",
                after_strategy="最后一帧",
                include_selected_debug=False,
                max_sequences="",
            )

            cfg = analyzer.config_from_gui_state(state)

            self.assertEqual(cfg.after_strategy, "last")

    def test_gui_state_requires_focus_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings = root / "settings.json"
            settings.write_text(
                '{"focus_guides":{"y_offset_mm":0},"peak_detect":{"difference_threshold":0.5,'
                '"roi2_extension_params":{"left":40,"right":40,"top":50,"bottom":30}}}',
                encoding="utf-8",
            )
            state = analyzer.GuiState(
                root_dir=str(root),
                output_csv=str(root / "summary.csv"),
                per_frame_csv="",
                settings_path=str(settings),
                focus_point="",
                focus_points_csv="",
                provider_depth_mm="",
                focus_y_offset_mm="0",
                roi2_left="40",
                roi2_right="40",
                roi2_top="50",
                roi2_bottom="30",
                difference_threshold="0.5",
                before_frame_index="1",
                after_strategy="roi2_peak",
                include_selected_debug=False,
                max_sequences="",
            )

            with self.assertRaisesRegex(ValueError, "必须填写全局焦点或选择焦点CSV"):
                analyzer.config_from_gui_state(state)

    def test_gui_settings_change_refreshes_roi2_and_focus_preview(self):
        class FakeVar:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class FakeRoot:
            def __init__(self):
                self.after_calls = []
                self.cancelled = []

            def after(self, delay_ms, callback, *args):
                self.after_calls.append((delay_ms, callback, args))
                callback(*args)
                return "after-id"

            def after_cancel(self, after_id):
                self.cancelled.append(after_id)

        class FakeStatus:
            def __init__(self):
                self.value = ""

            def set(self, value):
                self.value = value

        gui = object.__new__(analyzer.HemRoi2BatchAnalyzerGui)
        gui.root = FakeRoot()
        gui.focus_point = FakeVar("PointF(100, 100)")
        gui.focus_x = FakeVar("100")
        gui.focus_y = FakeVar("100")
        gui.root_dir = FakeVar(".")
        gui.output_csv = FakeVar("summary.csv")
        gui.per_frame_csv = FakeVar("")
        gui.settings_path = FakeVar("")
        gui.focus_points_csv = FakeVar("")
        gui.provider_depth_mm = FakeVar("100")
        gui.focus_y_offset_mm = FakeVar("0")
        gui.roi2_left = FakeVar("5")
        gui.roi2_right = FakeVar("5")
        gui.roi2_top = FakeVar("5")
        gui.roi2_bottom = FakeVar("5")
        gui.difference_threshold = FakeVar("0.5")
        gui.before_frame_index = FakeVar("1")
        gui.after_strategy = FakeVar("roi2_peak")
        gui.include_selected_debug = FakeVar(False)
        gui.max_sequences = FakeVar("")
        gui.status = FakeStatus()
        gui._preview_refresh_after_id = None
        gui._current_frame_paths = [Path("frame.png")]
        gui._step_sequence_dirs = [Path("seq")]
        gui._step_source_key = (".", False, "")
        gui._step_config_key = None

        calls = []
        gui.refresh_preview = lambda: calls.append(analyzer.config_from_gui_state(gui.current_state()))

        gui.roi2_left.set("20")
        gui._schedule_preview_refresh()
        self.assertEqual(calls[-1].roi2_extension_params["left"], 20)

        gui.focus_x.set("120")
        gui.focus_y.set("130")
        gui._schedule_preview_refresh()
        self.assertEqual(calls[-1].focus_point, "PointF(120.0, 130.0)")

    def test_gui_run_analysis_returns_immediately_while_one_sequence_runs(self):
        class FakeButton:
            def __init__(self):
                self.state_calls = []
                self.config_calls = []

            def state(self, values):
                self.state_calls.append(tuple(values))

            def configure(self, **kwargs):
                self.config_calls.append(kwargs)

        class FakeRoot:
            def __init__(self):
                self.after_calls = []

            def after(self, delay_ms, callback, *args):
                self.after_calls.append((delay_ms, callback, args))

        class FakeLabel:
            def __init__(self):
                self.configure_calls = []

            def configure(self, **kwargs):
                self.configure_calls.append(kwargs)

        class FakeScale:
            def __init__(self):
                self.configure_calls = []
                self.values = []

            def configure(self, **kwargs):
                self.configure_calls.append(kwargs)

            def set(self, value):
                self.values.append(value)

        gui = object.__new__(analyzer.HemRoi2BatchAnalyzerGui)
        gui.root = FakeRoot()
        gui.run_button = FakeButton()
        gui.image_label = FakeLabel()
        gui.timeline = FakeScale()
        gui.status = type("Status", (), {"set": lambda self, value: setattr(self, "value", value)})()
        gui.sequence_info = type("Status", (), {"set": lambda self, value: setattr(self, "value", value)})()
        gui.frame_info = type("Status", (), {"set": lambda self, value: setattr(self, "value", value)})()
        gui.show_roi2 = type("Var", (), {"get": lambda self: True})()
        gui.show_focus = type("Var", (), {"get": lambda self: True})()
        gui._analysis_running = False
        gui._step_config_key = None
        gui._step_source_key = None
        gui._step_sequence_dirs = []
        gui._step_next_index = 0
        gui._current_sequence_index = 0
        gui._step_summary_rows = []
        gui._step_frame_rows = []
        gui._analyzed_sequences = set()
        gui._current_frame_paths = []
        gui._current_frame_index = 0
        gui._current_preview_image = None
        gui._current_preview_meta = {}
        gui._photo_image = None
        gui._display_preview_image = lambda image: setattr(gui, "_current_preview_image", image)
        gui.current_state = lambda: analyzer.GuiState(
            root_dir=".",
            output_csv="summary.csv",
            per_frame_csv="",
            settings_path="",
            focus_point=analyzer.DEFAULT_FOCUS_POINT,
            focus_points_csv="",
            provider_depth_mm="",
            focus_y_offset_mm="0",
            roi2_left="40",
            roi2_right="40",
            roi2_top="50",
            roi2_bottom="30",
            difference_threshold="0.5",
            before_frame_index="1",
            after_strategy="roi2_peak",
            include_selected_debug=False,
            max_sequences="",
        )

        calls = []
        worker_started = threading.Event()
        release_worker = threading.Event()

        def slow_analyze_sequence(sequence_dir, config, focus_points):
            calls.append(sequence_dir.name)
            worker_started.set()
            release_worker.wait(0.5)
            return (
                {
                    "sequence": sequence_dir.name,
                    "status": "ok",
                    "error": "",
                    "frame_count": "0",
                    "focus_anchor": "",
                    "offset_anchor": "",
                    "roi2_rect": "",
                    "before_frame_index": "",
                    "before_frame": "",
                    "before_mean": "",
                    "after_frame_index": "",
                    "after_frame": "",
                    "after_mean": "",
                    "roi2_diff": "",
                    "difference_threshold": "",
                    "roi2_color": "red",
                    "after_strategy": "",
                },
                [],
            )

        def fail_analyze_root(config, progress_callback=None):
            raise AssertionError("GUI must not batch-analyze all sequences")

        original_sequence = analyzer.analyze_sequence
        original = analyzer.analyze_root
        import tkinter.messagebox as messagebox

        original_showinfo = messagebox.showinfo
        original_showerror = messagebox.showerror
        analyzer.analyze_sequence = slow_analyze_sequence
        analyzer.analyze_root = fail_analyze_root
        messagebox.showinfo = lambda *args, **kwargs: None
        messagebox.showerror = lambda *args, **kwargs: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                seq_a = root / "seq_a"
                seq_b = root / "seq_b"
                seq_a.mkdir()
                seq_b.mkdir()
                write_frame(seq_a / "00001_2026-06-14_00-00-00.000_frame.png", 10, size=(400, 400))
                write_frame(seq_b / "00001_2026-06-14_00-00-00.000_frame.png", 10, size=(400, 400))
                gui.current_state = lambda: analyzer.GuiState(
                    root_dir=str(root),
                    output_csv=str(root / "summary.csv"),
                    per_frame_csv="",
                    settings_path="",
                    focus_point=analyzer.DEFAULT_FOCUS_POINT,
                    focus_points_csv="",
                    provider_depth_mm="100",
                    focus_y_offset_mm="0",
                    roi2_left="40",
                    roi2_right="40",
                    roi2_top="50",
                    roi2_bottom="30",
                    difference_threshold="0.5",
                    before_frame_index="1",
                    after_strategy="roi2_peak",
                    include_selected_debug=False,
                    max_sequences="",
                )
                started = time.perf_counter()
                gui.run_analysis()
                elapsed = time.perf_counter() - started
                self.assertTrue(worker_started.wait(1.0))
        finally:
            release_worker.set()
            analyzer.analyze_sequence = original_sequence
            analyzer.analyze_root = original
            messagebox.showinfo = original_showinfo
            messagebox.showerror = original_showerror

        self.assertLess(elapsed, 0.1)
        self.assertEqual(gui.run_button.state_calls, [("disabled",)])
        self.assertTrue(gui._analysis_running)
        self.assertEqual(calls, ["seq_a"])

    def test_gui_stepwise_analysis_advances_one_sequence_per_click(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq_a = root / "seq_a"
            seq_b = root / "seq_b"
            seq_a.mkdir()
            seq_b.mkdir()
            write_frame(seq_a / "00001_2026-06-14_00-00-00.000_frame.png", 10, size=(400, 400))
            write_frame(seq_a / "00002_2026-06-14_00-00-00.070_frame.png", 20, size=(400, 400))
            write_frame(seq_b / "00001_2026-06-14_00-00-00.000_frame.png", 10, size=(400, 400))
            write_frame(seq_b / "00002_2026-06-14_00-00-00.070_frame.png", 12, size=(400, 400))

            cfg = analyzer.AnalyzerConfig(
                root_dir=root,
                output_csv=root / "summary.csv",
                per_frame_csv=root / "frames.csv",
                settings_path=None,
                focus_point="PointF(100, 100)",
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
            gui = object.__new__(analyzer.HemRoi2BatchAnalyzerGui)
            gui._step_config_key = None
            gui._step_sequence_dirs = []
            gui._step_next_index = 0
            gui._step_summary_rows = []
            gui._step_frame_rows = []

            gui._reset_step_state(cfg)
            focus_points = analyzer.load_focus_points_csv(cfg.focus_points_csv)
            first_row, first_frames = analyzer.analyze_sequence(gui._step_sequence_dirs[gui._step_next_index], cfg, focus_points)
            gui._step_summary_rows.append(first_row)
            gui._step_frame_rows.extend(first_frames)
            gui._step_next_index += 1
            analyzer.write_csv(cfg.output_csv, analyzer.SUMMARY_FIELDS, gui._step_summary_rows)
            analyzer.write_csv(cfg.per_frame_csv, analyzer.FRAME_FIELDS, gui._step_frame_rows)

            with cfg.output_csv.open("r", encoding="utf-8-sig", newline="") as f:
                saved = list(csv.DictReader(f))
            self.assertEqual([row["sequence"] for row in saved], ["seq_a"])

            second_row, second_frames = analyzer.analyze_sequence(gui._step_sequence_dirs[gui._step_next_index], cfg, focus_points)
            gui._step_summary_rows.append(second_row)
            gui._step_frame_rows.extend(second_frames)
            gui._step_next_index += 1
            analyzer.write_csv(cfg.output_csv, analyzer.SUMMARY_FIELDS, gui._step_summary_rows)
            analyzer.write_csv(cfg.per_frame_csv, analyzer.FRAME_FIELDS, gui._step_frame_rows)

            with cfg.output_csv.open("r", encoding="utf-8-sig", newline="") as f:
                saved = list(csv.DictReader(f))
            self.assertEqual([row["sequence"] for row in saved], ["seq_a", "seq_b"])
            self.assertEqual(gui._step_next_index, 2)


if __name__ == "__main__":
    unittest.main()
