import json
import logging
import errno
import sqlite3
from io import StringIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

import api_server


def make_state(
    usb: int = 1,
    control: int = 1,
    image: int = 1,
    app: int = 0,
    adb: int = 1,
    license_type: int = 1,
):
    return api_server.DeviceStateSnapshot(
        Version=1,
        AdbServer=adb,
        LicenseType=license_type,
        ControlLinkState=control,
        ImageInfoLinkState=image,
        USBLinkState=usb,
        AppRunState=app,
        ts=0.0,
    )


class ApiServerTests(unittest.TestCase):
    class WaitProbe:
        def __init__(self):
            self.calls = []

        def wait(self, timeout=None):
            self.calls.append(timeout)
            return True

        def is_set(self):
            return True

    class TimeoutProbe:
        def __init__(self):
            self.calls = []

        def wait(self, timeout=None):
            self.calls.append(timeout)
            return False

        def is_set(self):
            return False

    class FakeThread:
        def is_alive(self):
            return True

    class SequenceFrameSource:
        def __init__(self, frames):
            self._frames = list(frames)
            self._lock = threading.Lock()
            self._index = 0

        def __call__(self):
            with self._lock:
                if not self._frames:
                    return None
                if self._index >= len(self._frames):
                    return self._frames[-1]
                frame = self._frames[self._index]
                self._index += 1
                return frame

    def make_null_logger(self, name: str):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = False
        logger.addHandler(logging.NullHandler())
        return logger

    def make_stream_logger(self, name: str):
        stream = StringIO()
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        logger.addHandler(handler)
        return logger, stream

    def assert_pixel_near(self, image: np.ndarray, x: int, y: int, expected, radius: int = 2):
        height, width = image.shape[:2]
        for yy in range(max(0, y - radius), min(height, y + radius + 1)):
            for xx in range(max(0, x - radius), min(width, x + radius + 1)):
                if tuple(image[yy, xx][:3]) == tuple(expected):
                    return
        self.fail(f"expected color {expected} near ({x}, {y})")

    def create_segment_images_db_pair(self, root_dir: str, point_id: int = 123) -> None:
        for db_name in ("ccwssm", "zccwssm"):
            conn = sqlite3.connect(str(Path(root_dir) / db_name))
            try:
                conn.execute(
                    """
                    CREATE TABLE SegmentImagesInfo (
                        ID INTEGER PRIMARY KEY,
                        PointID INTEGER,
                        ImagePath VARCHAR(500),
                        TreatFlag TINYINT DEFAULT 0,
                        ErrorFlag TINYINT DEFAULT 0,
                        ModifyTime VARCHAR(100)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO SegmentImagesInfo
                        (ID, PointID, ImagePath, TreatFlag, ErrorFlag, ModifyTime)
                    VALUES (?, ?, '', 0, 0, '')
                    """,
                    (point_id, point_id),
                )
                conn.commit()
            finally:
                conn.close()

    def read_segment_treat_flags(self, root_dir: str, point_id: int = 123) -> dict[str, int]:
        flags: dict[str, int] = {}
        for db_name in ("ccwssm", "zccwssm"):
            conn = sqlite3.connect(str(Path(root_dir) / db_name))
            try:
                row = conn.execute(
                    "SELECT TreatFlag FROM SegmentImagesInfo WHERE ID = ?",
                    (point_id,),
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row, db_name)
            flags[db_name] = int(row[0])
        return flags

    def make_roi4_frame(self, base_value: int, roi4_value: int, seq: int) -> api_server.FrameSnapshot:
        image = np.full((520, 600, 3), base_value, dtype=np.uint8)
        image[306:495, 16:577] = roi4_value
        return api_server.FrameSnapshot(image, seq, float(seq))

    def make_roi4_records(self, frames=None):
        if frames is None:
            frames = [
                self.make_roi4_frame(10, 10, 1),
                self.make_roi4_frame(11, 10, 2),
                self.make_roi4_frame(60, 80, 3),
                self.make_roi4_frame(60, 80, 4),
                self.make_roi4_frame(20, 10, 5),
                self.make_roi4_frame(20, 10, 6),
                self.make_roi4_frame(12, 10, 7),
            ]
        return [
            api_server.OfflineFrameRecord(frame.image, frame.seq, frame.ts, index + 1, "frame", float(np.mean(frame.image)))
            for index, frame in enumerate(frames)
        ]

    def make_roi4_no_match_records(self):
        return self.make_roi4_records(
            [
            self.make_roi4_frame(10, 10, 1),
            self.make_roi4_frame(11, 10, 2),
            self.make_roi4_frame(60, 80, 3),
            self.make_roi4_frame(60, 80, 4),
            self.make_roi4_frame(20, 80, 5),
            self.make_roi4_frame(20, 80, 6),
            self.make_roi4_frame(12, 80, 7),
            ]
        )

    def make_roi4_manager(self, logger=None, roi4_rect=(16, 306, 577, 495)):
        return api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([]),
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi4_rect=roi4_rect,
                roi4_after_selector={
                    "enabled": True,
                    "block_size": 24,
                    "gray_diff_threshold": 15.0,
                    "candidate_area_ratio_threshold": 3.0,
                    "descent_low_frame_number": 2,
                },
                difference_threshold=5.0,
            ),
            logger=logger or self.make_null_logger("roi4_manager"),
        )

    def make_roi4_session(self, after_method: str, records=None) -> api_server.OfflineSession:
        if records is None:
            records = self.make_roi4_records()
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.initial_before_record = records[0]
        session.frame_buffer = records
        session.before = np.array(records[0].frame, copy=True)
        session.before_seq = records[0].seq
        session.before_ts = records[0].ts
        session.after = np.array(records[-1].frame, copy=True)
        session.after_seq = records[-1].seq
        session.after_ts = records[-1].ts
        session.after_method = after_method
        return session

    def test_parse_request_accepts_existing_protocol(self):
        parsed = api_server.parse_request('ONLINE;31415;{"point_id": 123}')

        self.assertEqual(parsed.req_type, "ONLINE")
        self.assertEqual(parsed.param, "31415")
        self.assertEqual(parsed.arg, '{"point_id": 123}')

    def test_resolve_runtime_dir_prefers_external_dir_when_local_files_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_dir = tmp_path / "local_pywrapper"
            external_dir = tmp_path / "external_pywrapper"
            local_dir.mkdir()
            external_dir.mkdir()
            for name in api_server.REQUIRED_RUNTIME_FILES:
                (external_dir / name).write_bytes(b"x")

            resolved = api_server.resolve_runtime_dir(
                base_dir=local_dir,
                external_runtime_dir=external_dir,
                env_runtime_dir=None,
            )

            self.assertEqual(resolved, external_dir)

    def test_resolve_runtime_dir_keeps_local_dir_when_required_files_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            local_dir = tmp_path / "local_pywrapper"
            external_dir = tmp_path / "external_pywrapper"
            local_dir.mkdir()
            external_dir.mkdir()
            for name in api_server.REQUIRED_RUNTIME_FILES:
                (local_dir / name).write_bytes(b"local")
                (external_dir / name).write_bytes(b"external")

            resolved = api_server.resolve_runtime_dir(
                base_dir=local_dir,
                external_runtime_dir=external_dir,
                env_runtime_dir=None,
            )

            self.assertEqual(resolved, local_dir)

    def test_convert_provider_data_matches_main_online_shape(self):
        raw = {
            "isLive": True,
            "mode": 2,
            "focus_depth": "7.5",
            "guankuan_a": "10.1",
            "guankuan_b": "20.2",
            "depth": "35",
            "focus_point": "F1",
        }

        self.assertEqual(
            api_server.convert_provider_data(raw),
            {
                "SkinDepth": 7.5,
                "A": 10.1,
                "B": 20.2,
                "Alpha": 0,
                "Depth": 35,
                "IsFreeze": False,
                "isHIFU": True,
                "FocusPoint": "F1",
            },
        )

    def test_convert_provider_data_uses_provider_alpha_value(self):
        raw = {
            "isLive": True,
            "mode": 1,
            "focus_depth": "7.5",
            "guankuan_a": "10.1",
            "guankuan_b": "20.2",
            "depth": "35",
            "focus_point": "F1",
            "Alpha": "12.345",
        }

        self.assertEqual(
            api_server.convert_provider_data(raw),
            {
                "SkinDepth": 7.5,
                "A": 10.1,
                "B": 20.2,
                "Alpha": 12.35,
                "Depth": 35,
                "IsFreeze": False,
                "isHIFU": False,
                "FocusPoint": "F1",
            },
        )

    def test_convert_provider_data_normalizes_online_numbers(self):
        raw = {
            "isLive": None,
            "mode": 1,
            "focus_depth": "7.555",
            "guankuan_a": "10.005",
            "guankuan_b": 20.0,
            "depth": None,
            "focus_point": None,
        }

        self.assertEqual(
            api_server.convert_provider_data(raw),
            {
                "SkinDepth": 7.56,
                "A": 10.01,
                "B": 20,
                "Alpha": 0,
                "Depth": None,
                "IsFreeze": None,
                "isHIFU": False,
                "FocusPoint": None,
            },
        )

    def test_convert_provider_data_keeps_non_numeric_values(self):
        raw = {
            "isLive": True,
            "mode": 1,
            "focus_depth": "",
            "guankuan_a": "NaN",
            "guankuan_b": "not-a-number",
            "depth": None,
            "focus_point": "PointF(434.85052, 272.8398)",
        }

        self.assertEqual(
            api_server.convert_provider_data(raw),
            {
                "SkinDepth": "",
                "A": "NaN",
                "B": "not-a-number",
                "Alpha": 0,
                "Depth": None,
                "IsFreeze": False,
                "isHIFU": False,
                "FocusPoint": "PointF(434.85052, 272.8398)",
            },
        )

    def test_online_reads_provider_and_returns_json(self):
        response = api_server.handle_request(
            'ONLINE;31415;{"point_id": 123}',
            provider_fetcher=lambda: {"isLive": False, "mode": 1, "depth": "40"},
        )

        payload = json.loads(response)
        self.assertEqual(payload["Depth"], 40)
        self.assertTrue(payload["IsFreeze"])
        self.assertFalse(payload["isHIFU"])
        self.assertEqual(payload["Alpha"], 0)

    def test_parse_focus_point_accepts_pointf_text(self):
        self.assertEqual(
            api_server.parse_focus_point("PointF(434.85052, 272.8398)"),
            (434, 272),
        )

    def test_compute_roi_region_uses_extension_params(self):
        self.assertEqual(
            api_server.compute_roi_region(
                (640, 480),
                (100, 120),
                {"left": 10, "right": 20, "top": 30, "bottom": 40},
            ),
            (90, 90, 120, 160),
        )

    def test_compute_roi_region_rejects_out_of_bounds(self):
        self.assertIsNone(
            api_server.compute_roi_region(
                (640, 480),
                (5, 120),
                {"left": 10, "right": 20, "top": 30, "bottom": 40},
            )
        )

    def test_parse_offline_config_reads_roi_and_debug_settings(self):
        config = api_server.parse_offline_config(
            {
                "offline_screenshot_test": {"enabled": True},
                "offline_peak": {
                    "enabled": True,
                    "threshold": 12.5,
                    "after_delay_frames": 3,
                    "end_diff_threshold": 4.5,
                },
                "peak_detect": {
                    "enabled": True,
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "roi4_rect": {"x": 16, "y": 306, "width": 561, "height": 189},
                    "difference_threshold": 1.5,
                    "roi4_after_selector": {
                        "enabled": True,
                        "block_size": 24,
                        "gray_diff_threshold": 15.0,
                        "candidate_area_ratio_threshold": 3.0,
                        "descent_low_frame_number": 2,
                    },
                    "roi3_g1_g2_override": {"enabled": True, "g1_threshold": 97.0, "g2_threshold": 18.0, "use_peak_max": False},
                    "roi3_column_diff_override": {"enabled": True, "g1_threshold": 98.0, "threshold": 11.0, "use_peak_max": False},
                },
                "offline_tmp_frames": {"enabled": True, "dir": "D:/software_data/tmp"},
                "offline_stop_wait_timeout_seconds": 8.0,
                "focus_guides": {"angle_degrees": 88.0, "line_width": 5, "y_offset_mm": 2.5},
            },
            self.make_null_logger("test_parse_offline_config_reads_roi_and_debug_settings"),
        )

        self.assertTrue(config.offline_peak_enabled)
        self.assertEqual(config.offline_peak_threshold, 12.5)
        self.assertEqual(config.offline_peak_after_delay_frames, 3)
        self.assertEqual(config.offline_peak_end_diff_threshold, 4.5)
        self.assertTrue(config.peak_detect_enabled)
        self.assertEqual(config.roi2_extension_params, {"left": 11, "right": 12, "top": 13, "bottom": 14})
        self.assertEqual(config.roi3_extension_params, {"left": 21, "right": 22, "top": 23, "bottom": 24})
        self.assertEqual(config.roi4_rect, (16, 306, 577, 495))
        self.assertIsNone(config.roi4_bottom_region_ratio)
        self.assertTrue(config.roi4_after_selector["enabled"])
        self.assertEqual(config.roi4_after_selector["block_size"], 24)
        self.assertEqual(config.roi4_after_selector["gray_diff_threshold"], 15.0)
        self.assertEqual(config.roi4_after_selector["candidate_area_ratio_threshold"], 3.0)
        self.assertEqual(config.roi4_after_selector["descent_low_frame_number"], 2)
        self.assertEqual(config.difference_threshold, 1.5)
        self.assertEqual(config.roi3_g1_g2_override["g1_threshold"], 97.0)
        self.assertEqual(config.roi3_column_diff_override["threshold"], 11.0)
        self.assertTrue(config.debug_save_enabled)
        self.assertEqual(config.debug_save_dir, "D:/software_data/tmp")
        self.assertEqual(config.stop_wait_timeout_seconds, 8.0)
        self.assertTrue(config.screenshot_test_enabled)
        self.assertEqual(config.focus_guide_angle_degrees, 88.0)
        self.assertEqual(config.focus_guide_line_width, 5)
        self.assertEqual(config.focus_y_offset_mm, 2.5)

    def test_parse_offline_config_defaults_focus_y_offset_to_one_mm(self):
        config = api_server.parse_offline_config(
            {
                "peak_detect": {
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "difference_threshold": 1.5,
                    "roi4_after_selector": {"enabled": False},
                },
                "offline_tmp_frames": {"enabled": False, "dir": "D:/software_data/tmp"},
            },
            self.make_null_logger("test_parse_offline_config_defaults_focus_y_offset_to_one_mm"),
        )

        self.assertEqual(config.focus_y_offset_mm, 1.0)
        self.assertEqual(config.frame_history_offset, 3)

    def test_parse_offline_config_reads_frame_history_offset(self):
        config = api_server.parse_offline_config(
            {
                "offline_frame_history_offset": 5,
                "peak_detect": {
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "difference_threshold": 1.5,
                    "roi4_after_selector": {"enabled": False},
                },
                "offline_tmp_frames": {"enabled": False, "dir": "D:/software_data/tmp"},
            },
            self.make_null_logger("test_parse_offline_config_reads_frame_history_offset"),
        )

        self.assertEqual(config.frame_history_offset, 5)

    def test_parse_offline_config_defaults_roi4_to_bottom_30_percent_when_selector_enabled(self):
        config = api_server.parse_offline_config(
            {
                "peak_detect": {
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "difference_threshold": 1.5,
                    "roi4_after_selector": {"enabled": True},
                },
                "offline_tmp_frames": {"enabled": True, "dir": "D:/software_data/tmp"},
            },
            self.make_null_logger("test_parse_offline_config_defaults_roi4_to_bottom_30_percent_when_selector_enabled"),
        )

        self.assertIsNone(config.roi4_rect)
        self.assertEqual(config.roi4_bottom_region_ratio, 0.3)

    def test_parse_offline_config_reads_configured_roi4_bottom_percent(self):
        config = api_server.parse_offline_config(
            {
                "peak_detect": {
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "difference_threshold": 1.5,
                    "roi4_bottom_region": {"height_ratio": 0.4},
                    "roi4_after_selector": {"enabled": True},
                },
                "offline_tmp_frames": {"enabled": True, "dir": "D:/software_data/tmp"},
            },
            self.make_null_logger("test_parse_offline_config_reads_configured_roi4_bottom_percent"),
        )

        self.assertIsNone(config.roi4_rect)
        self.assertEqual(config.roi4_bottom_region_ratio, 0.4)

    def test_resolve_roi4_rect_uses_bottom_percent_of_current_image(self):
        image = np.zeros((512, 542, 3), dtype=np.uint8)
        config = api_server.OfflineConfig(roi4_bottom_region_ratio=0.3)

        rect = api_server.resolve_roi4_rect_for_image(config, image)

        self.assertEqual(rect, (0, 358, 542, 512))

    def test_offline_uses_roi4_bottom_percent_region(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi4_bottom_region_ratio=0.25,
                    roi4_after_selector={
                        "enabled": True,
                        "block_size": 8,
                        "gray_diff_threshold": 15.0,
                        "candidate_area_ratio_threshold": 3.0,
                        "descent_low_frame_number": 2,
                    },
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=1.0,
                ),
                logger=self.make_null_logger("test_offline_uses_roi4_bottom_percent_region"),
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertEqual(stop["info"], "offline_stop_completed")
            self.assertEqual(stop["roi4_rect"], [0, 30, 40, 40])

    def test_roi4_candidate_area_ratio_uses_exact_edge_block_area(self):
        before = np.zeros((5, 5, 3), dtype=np.uint8)
        after = np.zeros((5, 5, 3), dtype=np.uint8)
        after[3:5, 3:5] = 20

        metrics = api_server.compute_roi4_mask_metrics(
            before,
            after,
            (0, 0, 5, 5),
            block_size=3,
            gray_diff_threshold=15.0,
        )

        self.assertEqual(metrics["candidate_block_count"], 1)
        self.assertAlmostEqual(metrics["candidate_area_ratio"], 16.0)
        self.assertAlmostEqual(metrics["largest_area_ratio"], 16.0)

    def test_parse_offline_config_reads_screenshot_roi_capture_region(self):
        config = api_server.parse_offline_config(
            {
                "offline_screenshot_test": {"enabled": True},
                "roi1_capture": {"enabled": True, "x1": 10, "y1": 20, "x2": 110, "y2": 220},
                "peak_detect": {
                    "enabled": False,
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "difference_threshold": 1.5,
                },
                "offline_peak": {"enabled": False},
                "offline_tmp_frames": {"enabled": False, "dir": "D:/software_data/tmp"},
            },
            self.make_null_logger("test_parse_offline_config_reads_screenshot_roi_capture_region"),
        )

        self.assertEqual(config.screenshot_capture_bbox, (10, 20, 110, 220))
        self.assertTrue(config.peak_detect_enabled)

    def test_parse_offline_config_forces_peak_detect_enabled(self):
        config = api_server.parse_offline_config(
            {
                "peak_detect": {
                    "enabled": False,
                    "roi2_extension_params": {"left": 11, "right": 12, "top": 13, "bottom": 14},
                    "roi3_extension_params": {"left": 21, "right": 22, "top": 23, "bottom": 24},
                    "difference_threshold": 1.5,
                },
                "offline_peak": {"enabled": False},
                "offline_tmp_frames": {"enabled": False, "dir": "D:/software_data/tmp"},
            },
            self.make_null_logger("test_parse_offline_config_forces_peak_detect_enabled"),
        )

        self.assertTrue(config.peak_detect_enabled)

    def test_default_settings_do_not_expose_peak_detect_enabled_switch(self):
        settings_text = Path(__file__).resolve().parents[2].joinpath("settings").read_text(encoding="utf-8")

        self.assertNotIn('"enabled": false', settings_text.split('"peak_detect":', 1)[1].split('"peak_debug_log"', 1)[0])

    def test_offline_requires_time_out_and_is_save_fields(self):
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=lambda: None,
            config=api_server.OfflineConfig.default(),
            logger=self.make_null_logger("test_offline_requires_time_out_and_is_save_fields"),
        )

        self.assertEqual(
            manager.handle('{"point_id": 123}'),
            {"success": False, "info": "missing_time_out", "point_id": 123},
        )
        self.assertEqual(
            manager.handle('{"point_id": 123, "time_out": 10}'),
            {"success": False, "info": "missing_is_save", "point_id": 123},
        )

    def test_offline_start_fails_without_device_frame(self):
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([]),
            config=api_server.OfflineConfig.default(),
            logger=self.make_null_logger("test_offline_start_fails_without_device_frame"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')

        self.assertEqual(start, {"success": True, "info": "offline_started", "point_id": 123})
        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_color"], "red")
        self.assertIsNone(stop["roi2_diff"])

    def test_offline_start_logs_missing_frame_diagnostics(self):
        logger, stream = self.make_stream_logger("test_offline_start_logs_missing_frame_diagnostics")
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([]),
            config=api_server.OfflineConfig.default(),
            logger=logger,
        )

        result = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')
        time.sleep(0.05)
        manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')

        self.assertEqual(result, {"success": True, "info": "offline_started", "point_id": 123})
        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag handle:", log_text)
        self.assertIn('"action": "start"', log_text)
        self.assertIn('"capture_source": "image_matrix"', log_text)
        self.assertIn("OFFLINE diag start_completed:", log_text)
        self.assertIn('"debug_save_enabled": false', log_text)
        self.assertIn("OFFLINE diag stop_decision:", log_text)

    def test_offline_start_fails_without_focus_point(self):
        frame = api_server.FrameSnapshot(np.zeros((20, 20, 3), dtype=np.uint8), 1, 1.0)
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {},
            frame_fetcher=self.SequenceFrameSource([frame]),
            config=api_server.OfflineConfig.default(),
            logger=self.make_null_logger("test_offline_start_fails_without_focus_point"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')

        self.assertEqual(start, {"success": True, "info": "offline_started", "point_id": 123})
        self.assertEqual(stop["roi2_color"], "red")
        self.assertIsNone(stop["focus_anchor"])

    def test_offline_two_signal_session_returns_green_roi2_result(self):
        frames = self.SequenceFrameSource([
            api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
        ])
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
            ),
            logger=self.make_null_logger("test_offline_two_signal_session_returns_green_roi2_result"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(start, {"success": True, "info": "offline_started", "point_id": 123})
        self.assertEqual(stop["success"], True)
        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_color"], "green")
        self.assertEqual(stop["focus_anchor"], [10, 10])
        self.assertEqual(stop["roi2_rect"], [8, 7, 12, 13])
        self.assertEqual(stop["roi3_rect"], [8, 7, 12, 13])
        self.assertEqual(stop["roi2_before_mean"], 10.0)
        self.assertEqual(stop["roi2_after_mean"], 20.0)
        self.assertEqual(stop["roi2_diff"], 10.0)

    def test_offline_green_path_logs_decision_details(self):
        logger, stream = self.make_stream_logger("test_offline_green_path_logs_decision_details")
        frames = self.SequenceFrameSource([
            api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
        ])
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
            ),
            logger=logger,
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_color"], "green")
        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag stop_decision:", log_text)
        self.assertIn('"roi2_before_mean": 10.0', log_text)
        self.assertIn('"roi2_after_mean": 20.0', log_text)
        self.assertIn('"roi2_diff": 10.0', log_text)
        self.assertIn('"threshold": 5.0', log_text)
        self.assertIn('"meets_threshold": true', log_text)
        self.assertIn('"roi2_color": "green"', log_text)
        self.assertIn('"debug_save_enabled": false', log_text)

    def test_offline_two_signal_session_returns_red_roi2_result(self):
        frames = self.SequenceFrameSource([
            api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((20, 20, 3), 12, dtype=np.uint8), 2, 2.0),
        ])
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
            ),
            logger=self.make_null_logger("test_offline_two_signal_session_returns_red_roi2_result"),
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_color"], "red")
        self.assertEqual(stop["roi2_diff"], 2.0)

    def test_offline_peak_detect_disabled_keeps_final_color_red(self):
        frames = [
            api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
        ]
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=lambda: frames.pop(0),
            config=api_server.OfflineConfig(
                peak_detect_enabled=False,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
            ),
            logger=self.make_null_logger("test_offline_peak_detect_disabled_keeps_final_color_red"),
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_color"], "red")

    def test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green(self):
        before = np.full((200, 200, 3), 10, dtype=np.uint8)
        after = np.full((200, 200, 3), 200, dtype=np.uint8)
        after[99:101, 99:101] = 12
        frames = [
            api_server.FrameSnapshot(before, 1, 1.0),
            api_server.FrameSnapshot(after, 2, 2.0),
        ]
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)", "depth": "1000"},
            frame_fetcher=lambda: frames.pop(0),
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 1, "right": 1, "top": 1, "bottom": 1},
                roi3_extension_params={"left": 50, "right": 50, "top": 50, "bottom": 50},
                difference_threshold=5.0,
                roi3_g1_g2_override={"enabled": True, "g1_threshold": 98.0, "g2_threshold": 20.0, "use_peak_max": False},
                roi3_column_diff_override={"enabled": False, "g1_threshold": 99.0, "threshold": 15.0, "use_peak_max": False},
                focus_y_offset_mm=0.0,
            ),
            logger=self.make_null_logger("test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green"),
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_diff"], 2.0)
        self.assertEqual(stop["roi2_color"], "red")
        self.assertFalse(stop["roi3_override_applied"])
        self.assertIsNone(stop["roi3_override_method"])

    def test_offline_roi2_rect_uses_focus_y_offset(self):
        frames = [
            api_server.FrameSnapshot(np.full((200, 200, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((200, 200, 3), 12, dtype=np.uint8), 2, 2.0),
        ]
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)", "depth": "100.0"},
            frame_fetcher=lambda: frames.pop(0),
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 5, "right": 5, "top": 6, "bottom": 6},
                roi3_extension_params={"left": 5, "right": 5, "top": 6, "bottom": 6},
                difference_threshold=5.0,
                focus_y_offset_mm=2.5,
            ),
            logger=self.make_null_logger("test_offline_roi2_rect_uses_focus_y_offset"),
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_rect"], [95, 99, 105, 111])

    def test_offline_peak_selection_uses_second_boundary_frames_not_stop_frame(self):
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 24, dtype=np.uint8), 4, 4.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 5, 5.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 6, 6.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 7, 7.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 8, 8.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 14, dtype=np.uint8), 9, 9.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 14, dtype=np.uint8), 10, 10.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                offline_peak_after_delay_frames=2,
                offline_peak_end_diff_threshold=7.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=5.0,
                stop_wait_timeout_seconds=2.0,
            ),
            logger=self.make_null_logger("test_offline_peak_selection_uses_second_boundary_frames_not_stop_frame"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        self.assertEqual(start["info"], "offline_started")
        time.sleep(0.15)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_before_mean"], 11.0)
        self.assertEqual(stop["roi2_after_mean"], 14.0)
        self.assertEqual(stop["roi2_color"], "red")
        self.assertEqual(stop["after_method"], "roi1_boundary_after2")

    def test_offline_peak_selection_uses_second_before_and_second_after_for_roi2(self):
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 24, dtype=np.uint8), 4, 4.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 5, 5.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 65, dtype=np.uint8), 6, 6.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 7, 7.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 13, dtype=np.uint8), 8, 8.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 14, dtype=np.uint8), 9, 9.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 14, dtype=np.uint8), 10, 10.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                offline_peak_after_delay_frames=0,
                offline_peak_end_diff_threshold=7.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=2.0,
                stop_wait_timeout_seconds=2.0,
                image_output_dir=None,
            ),
            logger=self.make_null_logger("test_offline_peak_selection_uses_second_before_and_second_after_for_roi2"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        self.assertEqual(start["info"], "offline_started")
        time.sleep(0.2)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_before_mean"], 11.0)
        self.assertEqual(stop["roi2_after_mean"], 14.0)
        self.assertEqual(stop["roi2_diff"], 3.0)
        self.assertEqual(stop["roi2_color"], "green")
        self.assertEqual(stop["after_method"], "roi1_boundary_after2")

    def test_offline_peak_selection_extends_shoulders_before_selecting_second_boundary_frames(self):
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 4, 4.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 19, dtype=np.uint8), 5, 5.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 22, dtype=np.uint8), 6, 6.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 35, dtype=np.uint8), 7, 7.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 18, dtype=np.uint8), 8, 8.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 16, dtype=np.uint8), 9, 9.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 10, 10.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 11, 11.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=20.0,
                offline_peak_end_diff_threshold=7.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=5.0,
                stop_wait_timeout_seconds=2.0,
            ),
            logger=self.make_null_logger("test_offline_peak_selection_extends_shoulders_before_selecting_second_boundary_frames"),
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.3)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_before_mean"], 10.0)
        self.assertEqual(stop["roi2_after_mean"], 10.0)
        self.assertEqual(stop["after_method"], "roi1_boundary_after2")

    def test_offline_peak_selection_fails_without_second_before_boundary_frame(self):
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                offline_peak_end_diff_threshold=7.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=2.0,
                stop_wait_timeout_seconds=2.0,
            ),
            logger=self.make_null_logger("test_offline_peak_selection_fails_without_second_before_boundary_frame"),
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.1)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertFalse(stop["success"])
        self.assertEqual(stop["info"], "error_in_detect")
        self.assertIn("at least two frames before", stop["error"])

    def test_offline_peak_failure_still_saves_img_and_tmp_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 3, 3.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    offline_peak_enabled=True,
                    offline_peak_threshold=25.0,
                    offline_peak_end_diff_threshold=7.0,
                    roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                    roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                    difference_threshold=2.0,
                    debug_save_enabled=True,
                    debug_save_dir=tmp,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_peak_failure_still_saves_img_and_tmp_artifacts"),
            )

            start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.1)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertFalse(stop["success"])
            self.assertEqual(stop["info"], "error_in_detect")
            self.assertIn("before_path", stop)
            self.assertIn("after_path", stop)
            self.assertIn("diff_path", stop)
            self.assertIn("debug_dir", stop)
            self.assertTrue(Path(stop["before_path"]).exists())
            self.assertTrue(Path(stop["after_path"]).exists())
            self.assertTrue(Path(stop["diff_path"]).exists())
            debug_dir = Path(start["debug_dir"])
            self.assertEqual(debug_dir, Path(stop["debug_dir"]))
            self.assertTrue((debug_dir / "final_before.png").exists())
            self.assertTrue((debug_dir / "final_after.png").exists())
            self.assertTrue((debug_dir / "meta.json").exists())

    def test_offline_peak_selection_falls_back_to_last_frame_when_second_after_boundary_frame_is_missing(self):
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                offline_peak_end_diff_threshold=7.0,
                roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                difference_threshold=2.0,
                stop_wait_timeout_seconds=2.0,
            ),
            logger=self.make_null_logger("test_offline_peak_selection_falls_back_to_last_frame_when_second_after_boundary_frame_is_missing"),
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.1)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_after_mean"], 12.0)
        self.assertEqual(stop["after_method"], "roi1_boundary_after2_fallback_last")

    def test_offline_roi4_selector_replaces_fallback_after_with_second_low_frame(self):
        frames = self.SequenceFrameSource(
            [
                self.make_roi4_frame(10, 10, 1),
                self.make_roi4_frame(11, 10, 2),
                self.make_roi4_frame(60, 80, 3),
                self.make_roi4_frame(60, 80, 4),
                self.make_roi4_frame(20, 10, 5),
                self.make_roi4_frame(20, 10, 6),
                self.make_roi4_frame(12, 10, 7),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi4_rect=(16, 306, 577, 495),
                roi4_after_selector={
                    "enabled": True,
                    "block_size": 24,
                    "gray_diff_threshold": 15.0,
                    "candidate_area_ratio_threshold": 3.0,
                    "descent_low_frame_number": 2,
                },
                difference_threshold=5.0,
            ),
            logger=self.make_null_logger("test_offline_roi4_selector_replaces_fallback_after_with_second_low_frame"),
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.1)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_color"], "green")
        self.assertTrue(stop["roi4_after_selector_applied"])
        self.assertEqual(stop["roi4_after_frame_index"], 6)
        self.assertEqual(stop["roi4_after_method"], "roi4_mask_descent_second")
        self.assertEqual(stop["after_seq"], 6)
        self.assertEqual(stop["roi4_rect"], [16, 306, 577, 495])
        self.assertAlmostEqual(stop["roi4_candidate_area_ratio"], 0.0)

    def test_offline_roi4_selector_is_primary_before_roi1_boundary_after(self):
        frames = self.SequenceFrameSource(
            [
                self.make_roi4_frame(10, 10, 1),
                self.make_roi4_frame(11, 10, 2),
                self.make_roi4_frame(60, 80, 3),
                self.make_roi4_frame(60, 80, 4),
                self.make_roi4_frame(20, 10, 5),
                self.make_roi4_frame(20, 10, 6),
                self.make_roi4_frame(12, 10, 7),
                self.make_roi4_frame(12, 10, 8),
                self.make_roi4_frame(12, 10, 9),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi4_rect=(16, 306, 577, 495),
                roi4_after_selector={
                    "enabled": True,
                    "block_size": 24,
                    "gray_diff_threshold": 15.0,
                    "candidate_area_ratio_threshold": 3.0,
                    "descent_low_frame_number": 2,
                },
                difference_threshold=5.0,
            ),
            logger=self.make_null_logger("test_offline_roi4_selector_is_primary_before_roi1_boundary_after"),
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.12)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertTrue(stop["roi4_after_selector_applied"])
        self.assertEqual(stop["roi4_after_frame_index"], 6)
        self.assertEqual(stop["roi4_after_method"], "roi4_mask_descent_second")
        self.assertEqual(stop["after_seq"], 6)
        self.assertEqual(stop["after_method"], "roi4_mask_descent_second")

    def test_offline_roi4_selector_preserves_fallback_after_without_low_high_low_sequence(self):
        frames = self.SequenceFrameSource(
            [
                self.make_roi4_frame(10, 10, 1),
                self.make_roi4_frame(11, 10, 2),
                self.make_roi4_frame(60, 80, 3),
                self.make_roi4_frame(60, 80, 4),
                self.make_roi4_frame(20, 80, 5),
                self.make_roi4_frame(20, 80, 6),
                self.make_roi4_frame(12, 80, 7),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi4_rect=(16, 306, 577, 495),
                roi4_after_selector={
                    "enabled": True,
                    "block_size": 24,
                    "gray_diff_threshold": 15.0,
                    "candidate_area_ratio_threshold": 3.0,
                    "descent_low_frame_number": 2,
                },
                difference_threshold=5.0,
            ),
            logger=self.make_null_logger("test_offline_roi4_selector_preserves_fallback_after_without_low_high_low_sequence"),
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.1)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertFalse(stop["roi4_after_selector_applied"])
        self.assertEqual(stop["after_seq"], 7)

    def test_roi4_selector_applies_to_all_fallback_after_methods(self):
        manager = self.make_roi4_manager()
        for method in sorted(api_server.ROI4_FALLBACK_AFTER_METHODS):
            with self.subTest(method=method):
                session = self.make_roi4_session(method)

                manager._apply_roi4_after_selector_if_needed(session)

                self.assertTrue(session.roi4_after_selector_applied)
                self.assertEqual(session.after_seq, 6)
                self.assertEqual(session.after_method, "roi4_mask_descent_second")

    def test_roi4_selector_does_not_affect_normal_boundary_after_method(self):
        manager = self.make_roi4_manager()
        session = self.make_roi4_session("roi1_boundary_after2")

        manager._apply_roi4_after_selector_if_needed(session)

        self.assertFalse(session.roi4_after_selector_applied)
        self.assertEqual(session.after_seq, 7)
        self.assertEqual(session.after_method, "roi1_boundary_after2")

    def test_roi4_selector_logs_state_transitions_for_selected_fallback(self):
        logger, stream = self.make_stream_logger("test_roi4_selector_logs_state_transitions_for_selected_fallback")
        manager = self.make_roi4_manager(logger=logger)
        session = self.make_roi4_session("stop_fallback")

        manager._apply_roi4_after_selector_if_needed(session)

        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag roi4_after_selector_begin:", log_text)
        self.assertIn('"original_after_method": "stop_fallback"', log_text)
        self.assertIn("OFFLINE diag roi4_after_selector_high_enter:", log_text)
        self.assertIn("OFFLINE diag roi4_after_selector_descent_low:", log_text)
        self.assertIn("OFFLINE diag roi4_after_selected:", log_text)
        self.assertIn('"frame_index": 6', log_text)
        self.assertIn('"candidate_area_ratio_threshold": 3.0', log_text)

    def test_roi4_selector_logs_skip_for_normal_after_method(self):
        logger, stream = self.make_stream_logger("test_roi4_selector_logs_skip_for_normal_after_method")
        manager = self.make_roi4_manager(logger=logger)
        session = self.make_roi4_session("roi1_boundary_after2")

        manager._apply_roi4_after_selector_if_needed(session)

        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag roi4_after_selector_skip:", log_text)
        self.assertIn('"reason": "after_method_not_fallback"', log_text)
        self.assertIn('"after_method": "roi1_boundary_after2"', log_text)

    def test_roi4_selector_logs_no_match_reason(self):
        logger, stream = self.make_stream_logger("test_roi4_selector_logs_no_match_reason")
        manager = self.make_roi4_manager(logger=logger)
        session = self.make_roi4_session("stop_fallback", self.make_roi4_no_match_records())

        manager._apply_roi4_after_selector_if_needed(session)

        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag roi4_after_selector_no_match:", log_text)
        self.assertIn('"reason": "no_low_high_low_sequence"', log_text)
        self.assertIn('"scanned_frame_count": 6', log_text)

    def test_roi4_selector_logs_failure_before_raising(self):
        logger, stream = self.make_stream_logger("test_roi4_selector_logs_failure_before_raising")
        manager = self.make_roi4_manager(logger=logger, roi4_rect=(16, 306, 9999, 9999))
        session = self.make_roi4_session("stop_fallback")

        with self.assertRaisesRegex(ValueError, "ROI4 rect outside image bounds"):
            manager._apply_roi4_after_selector_if_needed(session)

        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag roi4_after_selector_failed:", log_text)
        self.assertIn('"error": "ROI4 rect outside image bounds', log_text)

    def test_offline_invalid_roi4_rect_returns_error_without_stop_timeout(self):
        logger, stream = self.make_stream_logger("test_offline_invalid_roi4_rect_returns_error_without_stop_timeout")
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi4_rect=(0, 30, 50, 60),
                    roi4_after_selector={
                        "enabled": True,
                        "block_size": 24,
                        "gray_diff_threshold": 15.0,
                        "candidate_area_ratio_threshold": 3.0,
                        "descent_low_frame_number": 2,
                    },
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=1.0,
                ),
                logger=logger,
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertFalse(stop["success"])
            self.assertEqual(stop["info"], "error_in_detect")
            self.assertIn("ROI4 rect outside image bounds", stop["error"])
            self.assertIn("before_path", stop)
            self.assertIn("after_path", stop)
            log_text = stream.getvalue()
            self.assertIn("OFFLINE diag roi4_validate_end:", log_text)
            self.assertIn('"success": false', log_text)
            self.assertIn("OFFLINE diag finished_event_set:", log_text)
            self.assertIn('"response_info": "error_in_detect"', log_text)

    def test_offline_switch_waits_for_previous_capture_done_before_new_start(self):
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([]),
            config=api_server.OfflineConfig.default(),
            logger=self.make_null_logger("test_offline_switch_waits_for_previous_capture_done_before_new_start"),
        )
        probe = self.WaitProbe()
        previous = api_server.OfflineSession(
            point_id=111,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        previous.capture_done_event = probe
        previous.finished_event = threading.Event()
        previous.thread = self.FakeThread()
        manager._active_session = previous
        called = {}

        def fake_start(point_id, duration_s, is_save):
            called["point_id"] = point_id
            called["duration_s"] = duration_s
            called["is_save"] = is_save
            return {"success": True, "info": "offline_started", "point_id": point_id}

        manager._start_locked = fake_start

        result = manager.handle('{"point_id": 222, "time_out": 5, "is_save": false}')

        self.assertEqual(result, {"success": True, "info": "offline_started", "point_id": 222})
        self.assertTrue(previous.stop_event.is_set())
        self.assertEqual(probe.calls, [2])
        self.assertEqual(called, {"point_id": 222, "duration_s": 5.0, "is_save": False})

    def test_offline_switch_logs_wait_details(self):
        logger, stream = self.make_stream_logger("test_offline_switch_logs_wait_details")
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([]),
            config=api_server.OfflineConfig.default(),
            logger=logger,
        )
        probe = self.WaitProbe()
        previous = api_server.OfflineSession(
            point_id=111,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        previous.capture_done_event = probe
        previous.finished_event = threading.Event()
        previous.thread = self.FakeThread()
        manager._active_session = previous
        manager._start_locked = lambda point_id, duration_s, is_save: {"success": True, "info": "offline_started", "point_id": point_id}

        manager.handle('{"point_id": 222, "time_out": 5, "is_save": false}')

        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag handle:", log_text)
        self.assertIn('"action": "start"', log_text)
        self.assertIn("OFFLINE diag switch_wait_begin:", log_text)
        self.assertIn('"previous_point_id": 111', log_text)
        self.assertIn("OFFLINE diag switch_wait_completed:", log_text)
        self.assertIn('"capture_done_after_wait": true', log_text)

    def test_offline_stop_timeout_logs_last_finalization_stage(self):
        logger, stream = self.make_stream_logger("test_offline_stop_timeout_logs_last_finalization_stage")
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([]),
            config=api_server.OfflineConfig(stop_wait_timeout_seconds=1.0),
            logger=logger,
        )
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.finished_event = self.TimeoutProbe()
        session.capture_done_event = threading.Event()
        session.thread = self.FakeThread()
        session.finalization_stage = "save_debug_outputs"
        session.finalization_stage_started_ns = time.perf_counter_ns() - 150_000_000
        session.finalization_started_ns = time.perf_counter_ns() - 300_000_000

        result = manager._stop_locked(session)

        self.assertEqual(result["info"], "offline_stop_timeout")
        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag stop_wait_completed:", log_text)
        self.assertIn('"last_stage": "save_debug_outputs"', log_text)
        self.assertIn('"last_stage_elapsed_ms":', log_text)
        self.assertIn('"finalization_elapsed_ms":', log_text)

    def test_offline_debug_save_flushes_buffered_frames_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 3, 3.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 4, 4.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 6, 6.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    offline_peak_enabled=True,
                    offline_peak_threshold=25.0,
                    offline_peak_after_delay_frames=1,
                    offline_peak_end_diff_threshold=7.0,
                    roi2_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    debug_save_enabled=True,
                    debug_save_dir=tmp,
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_debug_save_flushes_buffered_frames_and_jsonl"),
            )

            start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.12)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            debug_dir = Path(start["debug_dir"])
            self.assertEqual(debug_dir, Path(stop["debug_dir"]))
            buffered = list(debug_dir.glob("0000*_*.png"))
            self.assertTrue(buffered)
            meta_jsonl = debug_dir / "offline_frames_meta.jsonl"
            self.assertTrue(meta_jsonl.exists())
            meta_lines = meta_jsonl.read_text(encoding="utf-8").splitlines()
            self.assertTrue(any('"event": "before_saved"' in line for line in meta_lines))
            self.assertTrue(any('"event": "after_saved"' in line for line in meta_lines))
            self.assertTrue(list(debug_dir.glob("selected_before_00001_*.png")))
            self.assertTrue(list(debug_dir.glob("selected_before_plus_offset_00004_*.png")))

    def test_offline_debug_final_before_after_names_include_source_frame_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 3, 3.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 4, 4.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 6, 6.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    offline_peak_enabled=True,
                    offline_peak_threshold=25.0,
                    roi2_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    debug_save_enabled=True,
                    debug_save_dir=tmp,
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_debug_final_before_after_names_include_source_frame_name"),
            )

            start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.12)
            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            debug_dir = Path(start["debug_dir"])
            before_files = [path.name for path in debug_dir.glob("final_before_*.png")]
            after_files = [path.name for path in debug_dir.glob("final_after_*.png")]
            self.assertEqual(len(before_files), 1)
            self.assertEqual(len(after_files), 1)
            self.assertTrue(before_files[0].startswith("final_before_00001_"))
            self.assertTrue(before_files[0].endswith("_frame.png"))
            self.assertTrue(after_files[0].startswith("final_after_00006_"))
            self.assertTrue(after_files[0].endswith("_frame.png"))

    def test_offline_peak_logs_threshold_and_after_selection(self):
        logger, stream = self.make_stream_logger("test_offline_peak_logs_threshold_and_after_selection")
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 4, 4.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 6, 6.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                offline_peak_enabled=True,
                offline_peak_threshold=25.0,
                offline_peak_after_delay_frames=1,
                offline_peak_end_diff_threshold=7.0,
                roi2_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                difference_threshold=5.0,
            ),
            logger=logger,
        )

        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        time.sleep(0.12)
        manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag session_thread_enter:", log_text)
        self.assertIn("OFFLINE diag before_captured:", log_text)
        self.assertIn("OFFLINE diag peak_threshold_initialized:", log_text)
        self.assertIn("OFFLINE diag before_selected:", log_text)
        self.assertIn("OFFLINE diag roi1_boundary_interval_selected:", log_text)
        self.assertIn("OFFLINE diag after_selected:", log_text)
        self.assertIn('"before_method": "roi1_boundary_before2"', log_text)
        self.assertIn('"after_method": "roi1_boundary_after2"', log_text)

    def test_offline_diff_image_contains_overlay_not_raw_positive_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((80, 80, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((80, 80, 3), 30, dtype=np.uint8), 2, 2.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(40, 40)", "depth": "80"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                    roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=None,
                ),
                logger=self.make_null_logger("test_offline_diff_image_contains_overlay_not_raw_positive_diff"),
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            diff_path = Path(stop["diff_path"])
            actual = np.array(api_server.Image.open(diff_path))
            raw = api_server.positive_diff_image(
                np.full((80, 80, 3), 10, dtype=np.uint8),
                np.full((80, 80, 3), 30, dtype=np.uint8),
            )
            self.assertFalse(np.array_equal(actual, raw))

    def test_diff_overlay_first_line_shows_actual_and_success_value(self):
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.roi2_diff = 2.0
        session.after_mean = 12.0
        session.before_mean = 10.0

        lines, line_ok = api_server.build_diff_overlay_judgement_lines(
            session,
            api_server.OfflineConfig(difference_threshold=5.0),
        )

        self.assertEqual(lines[0], "1. ROI2: current=2.000 / threshold=5.000")
        self.assertEqual(lines[1], "2. A:12.000,B:10.000,D:2.000")
        self.assertEqual(len(lines), 2)
        self.assertEqual(len(line_ok), 2)
        self.assertFalse(line_ok[0])
        self.assertNotIn("OK", lines[0])
        self.assertNotIn("FAIL", lines[0])

        session.roi2_diff = 8.0
        lines, line_ok = api_server.build_diff_overlay_judgement_lines(
            session,
            api_server.OfflineConfig(difference_threshold=5.0),
        )

        self.assertEqual(lines[0], "1. ROI2: current=8.000 / threshold=5.000")
        self.assertTrue(line_ok[0])

        session.roi2_diff = None
        lines, line_ok = api_server.build_diff_overlay_judgement_lines(
            session,
            api_server.OfflineConfig(difference_threshold=5.0),
        )

        self.assertEqual(lines[0], "1. ROI2: current=N/A / threshold=N/A")
        self.assertFalse(line_ok[0])

    def test_offline_diff_image_draws_roi_and_focus_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((160, 160, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((160, 160, 3), 30, dtype=np.uint8), 2, 2.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(80, 90)", "depth": "16"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 10, "right": 10, "top": 6, "bottom": 6},
                    roi3_extension_params={"left": 20, "right": 20, "top": 15, "bottom": 15},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=None,
                ),
                logger=self.make_null_logger("test_offline_diff_image_draws_roi_and_focus_markers"),
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            actual = np.array(api_server.Image.open(Path(stop["diff_path"])))
            self.assertNotEqual(tuple(actual[0, 0]), (255, 0, 0))
            self.assertEqual(tuple(actual[94, 80]), (0, 255, 0))
            self.assertNotEqual(tuple(actual[85, 80]), (255, 255, 0))
            self.assertEqual(tuple(actual[100, 80]), (128, 0, 128))

    def test_offline_diff_image_does_not_draw_roi4_marker(self):
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.before = np.full((80, 100, 3), 10, dtype=np.uint8)
        session.after = np.full((80, 100, 3), 30, dtype=np.uint8)
        session.roi4_rect = (10, 50, 90, 75)

        actual = api_server.render_diff_with_overlay(session, api_server.OfflineConfig())

        self.assertIsNotNone(actual)
        self.assertNotEqual(tuple(actual[50, 10]), api_server.ROI4_MARKER_COLOR)
        self.assertNotEqual(tuple(actual[74, 89]), api_server.ROI4_MARKER_COLOR)

    def test_offline_final_images_draw_focus_guides_on_before_after_and_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((200, 200, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((200, 200, 3), 30, dtype=np.uint8), 2, 2.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(100, 150)", "depth": "20"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 10, "right": 10, "top": 6, "bottom": 6},
                    roi3_extension_params={"left": 20, "right": 20, "top": 15, "bottom": 15},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=None,
                ),
                logger=self.make_null_logger("test_offline_final_images_draw_focus_guides_on_before_after_and_diff"),
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            before_actual = np.array(api_server.Image.open(Path(stop["before_path"])))
            after_actual = np.array(api_server.Image.open(Path(stop["after_path"])))
            diff_actual = np.array(api_server.Image.open(Path(stop["diff_path"])))
            guide_x = int(round(100 - np.sin(np.deg2rad(50.0)) * 30.0))
            shifted_focus_y = 160
            guide_y = int(round(shifted_focus_y - np.cos(np.deg2rad(50.0)) * 30.0))

            self.assertEqual(tuple(before_actual[0, 0][:3]), (10, 10, 10))
            self.assertEqual(tuple(after_actual[0, 0][:3]), (30, 30, 30))
            for actual in (before_actual, after_actual, diff_actual):
                self.assert_pixel_near(actual, guide_x, guide_y, (0, 255, 0))
            self.assertEqual(tuple(before_actual[shifted_focus_y, 100][:3]), (128, 0, 128))
            self.assertEqual(tuple(after_actual[shifted_focus_y, 100][:3]), (128, 0, 128))

    def test_offline_final_images_use_configured_focus_guide_angle_and_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((200, 200, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((200, 200, 3), 30, dtype=np.uint8), 2, 2.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(100, 150)", "depth": "20"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 10, "right": 10, "top": 6, "bottom": 6},
                    roi3_extension_params={"left": 20, "right": 20, "top": 15, "bottom": 15},
                    difference_threshold=5.0,
                    focus_guide_angle_degrees=60.0,
                    focus_guide_line_width=7,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=None,
                ),
                logger=self.make_null_logger("test_offline_final_images_use_configured_focus_guide_angle_and_width"),
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            before_actual = np.array(api_server.Image.open(Path(stop["before_path"])))
            guide_x = int(round(100 - np.sin(np.deg2rad(30.0)) * 30.0))
            shifted_focus_y = 160
            guide_y = int(round(shifted_focus_y - np.cos(np.deg2rad(30.0)) * 30.0))
            wide_x = int(round(guide_x - np.cos(np.deg2rad(30.0)) * 3.0))
            wide_y = int(round(guide_y + np.sin(np.deg2rad(30.0)) * 3.0))

            self.assert_pixel_near(before_actual, guide_x, guide_y, (0, 255, 0), radius=1)
            self.assert_pixel_near(before_actual, wide_x, wide_y, (0, 255, 0), radius=1)

    def test_focus_overlay_uses_default_one_mm_downward_offset(self):
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.focus_anchor = (80, 80)
        session.focus_depth_mm = 20.0
        frame = np.zeros((200, 200, 3), dtype=np.uint8)

        actual = api_server.render_frame_with_focus_guides(frame, session, api_server.OfflineConfig())

        self.assert_pixel_near(actual, 80, 90, api_server.FOCUS_MARKER_COLOR, radius=1)
        guide_x = int(round(80 - np.sin(np.deg2rad(50.0)) * 20.0))
        guide_y = int(round(90 - np.cos(np.deg2rad(50.0)) * 20.0))
        self.assert_pixel_near(actual, guide_x, guide_y, api_server.GUIDE_LINE_COLOR, radius=1)

    def test_focus_overlay_uses_configured_mm_offset_without_moving_roi_anchor(self):
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.focus_anchor = (100, 100)
        session.focus_depth_mm = 100.0
        session.roi2_rect = api_server.compute_roi_region(
            (200, 200),
            session.focus_anchor,
            {"left": 5, "right": 5, "top": 6, "bottom": 6},
        )
        frame = np.zeros((200, 200, 3), dtype=np.uint8)

        actual = api_server.render_frame_with_focus_guides(
            frame,
            session,
            api_server.OfflineConfig(focus_y_offset_mm=2.5),
        )

        self.assertEqual(session.roi2_rect, (95, 94, 105, 106))
        self.assert_pixel_near(actual, 100, 105, api_server.FOCUS_MARKER_COLOR, radius=1)

    def test_focus_overlay_positive_offset_requires_provider_depth(self):
        session = api_server.OfflineSession(
            point_id=123,
            duration_s=10.0,
            is_save=True,
            stop_event=threading.Event(),
        )
        session.focus_anchor = (80, 80)
        frame = np.zeros((200, 200, 3), dtype=np.uint8)

        with self.assertRaisesRegex(ValueError, "provider depth"):
            api_server.render_frame_with_focus_guides(frame, session, api_server.OfflineConfig())

    def test_positive_diff_image_ignores_alpha_channel_for_visible_png(self):
        before = np.zeros((4, 4, 4), dtype=np.uint8)
        after = np.zeros((4, 4, 4), dtype=np.uint8)
        before[:, :, :3] = 50
        after[:, :, :3] = 60
        before[:, :, 3] = 255
        after[:, :, 3] = 255

        diff = api_server.positive_diff_image(before, after)

        self.assertEqual(diff.shape, (4, 4, 3))
        self.assertEqual(int(np.max(diff)), 10)

    def test_offline_output_logs_flush_and_output_paths(self):
        logger, stream = self.make_stream_logger("test_offline_output_logs_flush_and_output_paths")
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 11, dtype=np.uint8), 2, 2.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 3, 3.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 4, 4.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 6, 6.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    offline_peak_enabled=True,
                    offline_peak_threshold=25.0,
                    offline_peak_after_delay_frames=1,
                    offline_peak_end_diff_threshold=7.0,
                    roi2_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 3, "right": 3, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    debug_save_enabled=True,
                    debug_save_dir=tmp,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=logger,
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.12)
            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            log_text = stream.getvalue()
            self.assertIn("OFFLINE diag save_debug_outputs_begin:", log_text)
            self.assertIn("OFFLINE diag buffer_flush_begin:", log_text)
            self.assertIn("OFFLINE diag buffer_flush_completed:", log_text)
            self.assertIn("OFFLINE diag save_debug_outputs_end:", log_text)
            self.assertIn("OFFLINE diag result_flag_written:", log_text)
            self.assertIn("OFFLINE diag final_outputs_saved:", log_text)
            self.assertIn('"meta_jsonl":', log_text)
            self.assertIn('"diff_path":', log_text)

    def test_offline_green_save_logs_main_program_state_sync(self):
        logger, stream = self.make_stream_logger("test_offline_green_save_logs_main_program_state_sync")
        with tempfile.TemporaryDirectory() as tmp:
            self.create_segment_images_db_pair(tmp)
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=tmp,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=logger,
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertEqual(stop["roi2_color"], "green")
            log_text = stream.getvalue()
            self.assertIn("OFFLINE diag main_program_state_sync_begin:", log_text)
            self.assertIn("OFFLINE diag save_final_outputs_begin:", log_text)
            self.assertIn("OFFLINE diag write_before_begin:", log_text)
            self.assertIn("OFFLINE diag write_before_end:", log_text)
            self.assertIn("OFFLINE diag write_after_begin:", log_text)
            self.assertIn("OFFLINE diag render_diff_begin:", log_text)
            self.assertIn("OFFLINE diag write_diff_end:", log_text)
            self.assertIn("OFFLINE diag db_update_begin:", log_text)
            self.assertIn("OFFLINE diag result_flag_written:", log_text)
            self.assertIn("OFFLINE diag db_update_completed:", log_text)
            self.assertIn("OFFLINE diag save_final_outputs_end:", log_text)
            self.assertIn("OFFLINE diag finished_event_set:", log_text)
            self.assertIn("OFFLINE diag final_response_ready:", log_text)
            self.assertIn('"elapsed_ms":', log_text)
            self.assertIn('"roi2_color": "green"', log_text)
            self.assertIn('"treatment_ok": true', log_text)
            self.assertIn('"result_flag_value": "1"', log_text)
            self.assertIn('"response_success": true', log_text)
            self.assertIn('"response_info": "offline_stop_completed"', log_text)

    def test_offline_save_updates_db_image_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=tmp,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_save_updates_db_image_paths"),
            )

            with patch("api_server.update_segment_images_info") as update_mock:
                manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
                time.sleep(0.05)
                stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertEqual(stop["info"], "offline_stop_completed")
            update_mock.assert_called_once()
            db_root_arg, point_id_arg, before_path_arg, after_path_arg, treatment_ok_arg = update_mock.call_args.args
            self.assertEqual(db_root_arg, tmp)
            self.assertEqual(point_id_arg, 123)
            self.assertEqual(before_path_arg, stop["before_path"])
            self.assertEqual(after_path_arg, stop["after_path"])
            self.assertTrue(treatment_ok_arg)
            self.assertTrue(Path(stop["before_path"]).exists())
            self.assertTrue(Path(stop["after_path"]).exists())
            self.assertTrue(Path(stop["diff_path"]).exists())

    def test_offline_green_save_updates_db_treat_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.create_segment_images_db_pair(tmp)
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=tmp,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_green_save_updates_db_treat_flag"),
            )

            manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertEqual(stop["info"], "offline_stop_completed")
            self.assertEqual(stop["roi2_color"], "green")
            self.assertEqual(self.read_segment_treat_flags(tmp), {"ccwssm": 1, "zccwssm": 1})

    def test_offline_db_update_failure_returns_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=tmp,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_db_update_failure_returns_error"),
            )

            with patch("api_server.update_segment_images_info", side_effect=RuntimeError("db write blocked")):
                manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
                time.sleep(0.05)
                stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertFalse(stop["success"])
            self.assertEqual(stop["info"], "db_update_failed")
            self.assertIn("db write blocked", stop["error"])

    def test_offline_db_update_failure_still_saves_debug_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    difference_threshold=5.0,
                    debug_save_enabled=True,
                    debug_save_dir=tmp,
                    image_output_dir=tmp,
                    db_root_dir=tmp,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_db_update_failure_still_saves_debug_artifacts"),
            )

            with patch("api_server.update_segment_images_info", side_effect=RuntimeError("db write blocked")):
                start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
                time.sleep(0.05)
                stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertFalse(stop["success"])
            self.assertEqual(stop["info"], "db_update_failed")
            debug_dir = Path(start["debug_dir"])
            self.assertEqual(debug_dir, Path(stop["debug_dir"]))
            self.assertTrue((debug_dir / "final_before.png").exists())
            self.assertTrue((debug_dir / "final_after.png").exists())
            self.assertTrue((debug_dir / "meta.json").exists())

    def test_offline_detect_failure_still_attempts_db_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    offline_peak_enabled=True,
                    offline_peak_threshold=25.0,
                    offline_peak_end_diff_threshold=7.0,
                    roi2_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                    roi3_extension_params={"left": 5, "right": 5, "top": 5, "bottom": 5},
                    difference_threshold=2.0,
                    image_output_dir=tmp,
                    db_root_dir=tmp,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=self.make_null_logger("test_offline_detect_failure_still_attempts_db_update"),
            )

            with patch("api_server.update_segment_images_info") as update_mock:
                manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
                time.sleep(0.1)
                stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertFalse(stop["success"])
            self.assertEqual(stop["info"], "error_in_detect")
            self.assertEqual(stop["roi2_color"], "green")
            self.assertTrue(stop["treatment_ok"])
            update_mock.assert_called_once()
            self.assertEqual(update_mock.call_args.args[1], 123)
            self.assertEqual(update_mock.call_args.args[2], stop["before_path"])
            self.assertEqual(update_mock.call_args.args[3], stop["after_path"])
            self.assertTrue(update_mock.call_args.args[4])

    def test_offline_red_path_logs_decision_details(self):
        logger, stream = self.make_stream_logger("test_offline_red_path_logs_decision_details")
        frames = self.SequenceFrameSource([
            api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((20, 20, 3), 12, dtype=np.uint8), 2, 2.0),
        ])
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=frames,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                difference_threshold=5.0,
            ),
            logger=logger,
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_color"], "red")
        log_text = stream.getvalue()
        self.assertIn("OFFLINE diag stop_decision:", log_text)
        self.assertIn('"roi2_before_mean": 10.0', log_text)
        self.assertIn('"roi2_after_mean": 12.0', log_text)
        self.assertIn('"roi2_diff": 2.0', log_text)
        self.assertIn('"threshold": 5.0', log_text)
        self.assertIn('"meets_threshold": false', log_text)
        self.assertIn('"roi2_color": "red"', log_text)
        self.assertIn('"debug_save_enabled": false', log_text)

    def test_offline_debug_save_writes_before_after_roi_images_and_meta(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource([
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ])
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=frames,
                config=api_server.OfflineConfig(
                    peak_detect_enabled=True,
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 4, "right": 4, "top": 5, "bottom": 5},
                    difference_threshold=5.0,
                    debug_save_enabled=True,
                    debug_save_dir=tmp,
                ),
                logger=self.make_null_logger("test_offline_debug_save_writes_before_after_roi_images_and_meta"),
            )

            start = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

            debug_dir = Path(start["debug_dir"])
            self.assertEqual(debug_dir, Path(stop["debug_dir"]))
            for name in (
                "before_roi1.png",
                "before_roi2.png",
                "before_roi3.png",
                "after_roi1.png",
                "after_roi2.png",
                "after_roi3.png",
                "meta.json",
            ):
                self.assertTrue((debug_dir / name).exists(), name)
            meta = json.loads((debug_dir / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["point_id"], 123)
            self.assertEqual(meta["focus_anchor"], [10, 10])
            self.assertEqual(meta["roi2_rect"], [8, 7, 12, 13])
            self.assertEqual(meta["roi3_rect"], [6, 5, 14, 15])
            self.assertEqual(meta["result"]["roi2_color"], "green")

    def test_offline_debug_disabled_does_not_create_debug_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = [
                api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((20, 20, 3), 20, dtype=np.uint8), 2, 2.0),
            ]
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
                frame_fetcher=lambda: frames.pop(0),
                config=api_server.OfflineConfig(
                    roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                    roi3_extension_params={"left": 4, "right": 4, "top": 5, "bottom": 5},
                    difference_threshold=5.0,
                    debug_save_enabled=False,
                    debug_save_dir=tmp,
                ),
                logger=self.make_null_logger("test_offline_debug_disabled_does_not_create_debug_dir"),
            )

            start = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
            stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

            self.assertNotIn("debug_dir", start)
            self.assertNotIn("debug_dir", stop)
            self.assertFalse((Path(tmp) / "pywrapper_offline").exists())

    def test_offline_start_fails_when_roi3_is_out_of_bounds(self):
        frame = api_server.FrameSnapshot(np.zeros((20, 20, 3), dtype=np.uint8), 1, 1.0)
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=self.SequenceFrameSource([frame]),
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 30, "right": 4, "top": 5, "bottom": 5},
                difference_threshold=5.0,
                debug_save_enabled=False,
                debug_save_dir="D:/software_data/tmp",
            ),
            logger=self.make_null_logger("test_offline_start_fails_when_roi3_is_out_of_bounds"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')
        time.sleep(0.05)
        stop = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')

        self.assertEqual(start, {"success": True, "info": "offline_started", "point_id": 123})
        self.assertEqual(stop["roi2_color"], "red")
        self.assertIsNone(stop["roi3_rect"])

    def test_offline_debug_save_failure_returns_error(self):
        class FailingSaver(api_server.DebugFrameSaver):
            def save_stage(self, *args, **kwargs):
                raise OSError("disk blocked")

        frame_source = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.zeros((20, 20, 3), dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.zeros((20, 20, 3), dtype=np.uint8), 2, 2.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)", "depth": "1000"},
            frame_fetcher=frame_source,
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 2, "right": 2, "top": 3, "bottom": 3},
                roi3_extension_params={"left": 4, "right": 4, "top": 5, "bottom": 5},
                difference_threshold=5.0,
                debug_save_enabled=True,
                debug_save_dir="D:/software_data/tmp",
            ),
            logger=self.make_null_logger("test_offline_debug_save_failure_returns_error"),
            debug_saver=FailingSaver(),
        )

        start = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')
        self.assertEqual(start["info"], "offline_started")
        time.sleep(0.05)
        result = manager.handle('{"point_id": 123, "time_out": 1, "is_save": true}')

        self.assertEqual(result["success"], False)
        self.assertEqual(result["info"], "debug_save_failed")
        self.assertEqual(result["point_id"], 123)

    def test_offline_screenshot_mode_uses_screenshot_capture_source_and_returns_outputs(self):
        screenshot_frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((80, 80, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((80, 80, 3), 30, dtype=np.uint8), 2, 2.0),
            ]
        )
        logger, stream = self.make_stream_logger("test_offline_screenshot_mode_uses_screenshot_capture_source_and_returns_outputs")
        with tempfile.TemporaryDirectory() as tmp:
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(40, 40)", "depth": "1000"},
                frame_fetcher=lambda: None,
                config=api_server.OfflineConfig(
                    screenshot_test_enabled=True,
                    screenshot_capture_bbox=(0, 0, 80, 80),
                    peak_detect_enabled=False,
                    difference_threshold=5.0,
                    image_output_dir=tmp,
                    db_root_dir=None,
                    result_flag_path=str(Path(tmp) / "result.txt"),
                    stop_wait_timeout_seconds=2.0,
                ),
                logger=logger,
                screenshot_frame_fetcher=screenshot_frames,
            )

            start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
            time.sleep(0.05)
            stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

            self.assertEqual(start["info"], "offline_started")
            self.assertEqual(stop["info"], "offline_stop_completed")
            self.assertEqual(stop["roi2_color"], "red")
            self.assertIn("before_path", stop)
            self.assertIn("after_path", stop)
            self.assertIn("diff_path", stop)
            log_text = stream.getvalue()
            self.assertIn('"capture_source": "screenshot"', log_text)

    def test_unknown_request_returns_failure(self):
        response = api_server.handle_request("OCR;31415;{}", provider_fetcher=lambda: {})

        self.assertEqual(
            json.loads(response),
            {"success": False, "info": "unknown_request_type", "req_type": "OCR"},
        )

    def test_wrong_password_returns_failure(self):
        response = api_server.handle_request("ONLINE;bad;{}", provider_fetcher=lambda: {})

        self.assertEqual(json.loads(response), {"success": False, "info": "invalid_password"})

    def test_shutdown_request_triggers_handler_with_valid_password(self):
        shutdown_calls = []

        response = api_server.handle_request(
            "SHUTDOWN;31415",
            provider_fetcher=lambda: {},
            shutdown_handler=lambda: shutdown_calls.append("called"),
        )

        self.assertEqual(
            json.loads(response),
            {"success": True, "info": "shutdown_requested"},
        )
        self.assertEqual(shutdown_calls, ["called"])

    def test_shutdown_request_with_wrong_password_does_not_trigger_handler(self):
        shutdown_handler = Mock()

        response = api_server.handle_request(
            "SHUTDOWN;bad",
            provider_fetcher=lambda: {},
            shutdown_handler=shutdown_handler,
        )

        self.assertEqual(json.loads(response), {"success": False, "info": "invalid_password"})
        shutdown_handler.assert_not_called()

    def test_build_server_socket_reports_already_running_when_pywrapper_owns_port(self):
        class BindInUseSocket:
            def __init__(self, *args, **kwargs):
                self.closed = False
                self.options = []

            def setsockopt(self, level, option, value):
                self.options.append((level, option, value))

            def bind(self, addr):
                exc = OSError("address in use")
                exc.errno = errno.EADDRINUSE
                exc.winerror = 10048
                raise exc

            def close(self):
                self.closed = True

        fake_socket = BindInUseSocket()
        original_socket_factory = api_server.socket.socket
        original_probe = getattr(api_server, "probe_pywrapper_server", None)
        try:
            api_server.socket.socket = lambda *args, **kwargs: fake_socket
            api_server.probe_pywrapper_server = lambda host, port, timeout_s=0.5: True

            with self.assertRaisesRegex(RuntimeError, "already running"):
                api_server.build_server_socket(
                    "127.0.0.1",
                    30415,
                    logger=self.make_null_logger("test_build_server_socket_reports_already_running_when_pywrapper_owns_port"),
                )
        finally:
            api_server.socket.socket = original_socket_factory
            if original_probe is None:
                delattr(api_server, "probe_pywrapper_server")
            else:
                api_server.probe_pywrapper_server = original_probe

        self.assertTrue(fake_socket.closed)

    def test_build_server_socket_reports_foreign_port_conflict(self):
        class BindInUseSocket:
            def __init__(self, *args, **kwargs):
                self.closed = False

            def setsockopt(self, level, option, value):
                pass

            def bind(self, addr):
                exc = OSError("address in use")
                exc.errno = errno.EADDRINUSE
                exc.winerror = 10048
                raise exc

            def close(self):
                self.closed = True

        fake_socket = BindInUseSocket()
        original_socket_factory = api_server.socket.socket
        original_probe = getattr(api_server, "probe_pywrapper_server", None)
        try:
            api_server.socket.socket = lambda *args, **kwargs: fake_socket
            api_server.probe_pywrapper_server = lambda host, port, timeout_s=0.5: False

            with self.assertRaisesRegex(RuntimeError, "occupied by another process"):
                api_server.build_server_socket(
                    "127.0.0.1",
                    30415,
                    logger=self.make_null_logger("test_build_server_socket_reports_foreign_port_conflict"),
                )
        finally:
            api_server.socket.socket = original_socket_factory
            if original_probe is None:
                delattr(api_server, "probe_pywrapper_server")
            else:
                api_server.probe_pywrapper_server = original_probe

        self.assertTrue(fake_socket.closed)

    def test_online_logs_raw_provider_data_and_missing_fields(self):
        stream = StringIO()
        logger = logging.getLogger("test_online_logs_raw_provider_data_and_missing_fields")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        logger.addHandler(handler)

        response = api_server.handle_request(
            'ONLINE;31415;{}',
            provider_fetcher=lambda: {"isLive": True},
            logger=logger,
        )

        self.assertEqual(json.loads(response)["IsFreeze"], False)
        log_text = stream.getvalue()
        self.assertIn('ONLINE raw provider data: {"isLive": true}', log_text)
        self.assertIn("ONLINE missing provider fields:", log_text)
        self.assertIn("focus_depth", log_text)
        self.assertIn("guankuan_a", log_text)
        self.assertIn("guankuan_b", log_text)
        self.assertIn("depth", log_text)
        self.assertIn("focus_point", log_text)

    def test_online_logs_final_response_json(self):
        logger, stream = self.make_stream_logger("test_online_logs_final_response_json")

        response = api_server.handle_request(
            'ONLINE;31415;{}',
            provider_fetcher=lambda: {
                "isLive": True,
                "mode": 2,
                "focus_depth": "7.5",
                "guankuan_a": "10.1",
                "guankuan_b": "20.2",
                "depth": "35",
            },
            logger=logger,
        )

        log_text = stream.getvalue()
        self.assertIn("ONLINE response JSON:", log_text)
        self.assertIn('"SkinDepth": 7.5', log_text)
        self.assertIn('"A": 10.1', log_text)
        self.assertEqual(json.loads(response)["Depth"], 35)

    def test_online_logs_timepoints(self):
        stream = StringIO()
        logger = logging.getLogger("test_online_logs_timepoints")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        logger.addHandler(handler)

        response = api_server.handle_request(
            'ONLINE;31415;{}',
            provider_fetcher=lambda: {"isLive": True, "mode": 2, "focus_depth": "6.5"},
            logger=logger,
            trace_id="unit-trace",
        )

        self.assertEqual(json.loads(response)["SkinDepth"], 6.5)
        log_text = stream.getvalue()
        self.assertIn("ONLINE timepoint trace_id=unit-trace | step=handle_request_entered | wall_time=", log_text)
        self.assertIn("step=provider_fetch_start", log_text)
        self.assertIn("step=provider_fetch_completed", log_text)
        self.assertIn("step=convert_provider_completed", log_text)
        self.assertIn("step=json_encode_completed", log_text)
        self.assertIn("perf_counter_ns=", log_text)

    def test_mobile_comm_engine_configures_callbacks_and_d3d_window(self):
        comm = Mock()
        logger = logging.getLogger("test_mobile_comm_engine_configures_callbacks_and_d3d_window")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())

        engine = api_server.MobileCommEngine(
            comm,
            logger,
            hwnd_factory=lambda: 12345,
            hwnd_destroyer=lambda hwnd: None,
            stream_interval_s=0.01,
        )

        engine.configure()

        comm.SetOnImageInfoOnceMsg.assert_called_once()
        comm.SetOnClientStateInfoOnceMsg.assert_called_once()
        comm.SetD3DRenderHWND.assert_called_once_with(12345)

    def test_mobile_comm_engine_caches_latest_device_state(self):
        comm = Mock()
        logger = self.make_null_logger("test_mobile_comm_engine_caches_latest_device_state")
        engine = api_server.MobileCommEngine(
            comm,
            logger,
            hwnd_factory=lambda: 12345,
            hwnd_destroyer=lambda hwnd: None,
            stream_interval_s=0.01,
        )
        state = api_server.StateInfo(
            Version=1,
            AdbServer=1,
            LicenseType=1,
            ControlLinkState=1,
            ImageInfoLinkState=1,
            USBLinkState=1,
            AppRunState=0,
        )

        engine._on_state_info_received(api_server.ctypes.addressof(state))

        snapshot = engine.get_latest_state()
        self.assertEqual(snapshot.ControlLinkState, 1)
        self.assertEqual(snapshot.ImageInfoLinkState, 1)
        self.assertEqual(snapshot.USBLinkState, 1)

    def test_mobile_comm_engine_caches_latest_device_state_without_info_log(self):
        comm = Mock()
        logger, stream = self.make_stream_logger("test_mobile_comm_engine_caches_latest_device_state_without_info_log")
        engine = api_server.MobileCommEngine(
            comm,
            logger,
            hwnd_factory=lambda: 12345,
            hwnd_destroyer=lambda hwnd: None,
            stream_interval_s=0.01,
        )
        state = api_server.StateInfo(
            Version=1,
            AdbServer=1,
            LicenseType=1,
            ControlLinkState=0,
            ImageInfoLinkState=0,
            USBLinkState=0,
            AppRunState=0,
        )

        engine._on_state_info_received(api_server.ctypes.addressof(state))

        snapshot = engine.get_latest_state()
        self.assertEqual(snapshot.ControlLinkState, 0)
        self.assertEqual(snapshot.ImageInfoLinkState, 0)
        self.assertEqual(snapshot.USBLinkState, 0)
        self.assertNotIn("device state:", stream.getvalue())

    def test_mobile_comm_engine_caches_latest_frame_without_info_log(self):
        comm = Mock()
        logger, stream = self.make_stream_logger("test_mobile_comm_engine_caches_latest_frame_without_info_log")
        engine = api_server.MobileCommEngine(
            comm,
            logger,
            hwnd_factory=lambda: 12345,
            hwnd_destroyer=lambda hwnd: None,
            stream_interval_s=0.01,
        )
        image = np.zeros((512, 600, 4), dtype=np.uint8)

        engine._on_image_info_received(140723069053216, image)

        frame = engine.get_latest_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.image.shape, (512, 600, 4))
        self.assertEqual(frame.seq, 1)
        self.assertNotIn("image callback received", stream.getvalue())

    def test_mobile_comm_engine_returns_configured_history_frame(self):
        comm = Mock()
        logger = self.make_null_logger("test_mobile_comm_engine_returns_configured_history_frame")
        engine = api_server.MobileCommEngine(
            comm,
            logger,
            hwnd_factory=lambda: 12345,
            hwnd_destroyer=lambda hwnd: None,
            stream_interval_s=0.01,
            frame_history_offset=3,
        )

        for value in range(1, 6):
            image = np.full((2, 2, 1), value, dtype=np.uint8)
            engine._on_image_info_received(None, image)

        frame = engine.get_latest_frame()
        self.assertIsNotNone(frame)
        self.assertEqual(frame.seq, 2)
        self.assertEqual(int(frame.image[0, 0, 0]), 2)

    def make_provider_for_reconnect_tests(self, states):
        provider = object.__new__(api_server.PyMobileCommProvider)
        provider._logger = self.make_null_logger("provider_reconnect_test")
        provider._comm = Mock()
        provider._lock = threading.Lock()
        provider._request_state_lock = threading.Lock()
        provider._pending_provider_event = None
        provider._pending_provider_payload = None
        provider._pending_provider_error = None
        engine = Mock()
        engine.get_latest_state.side_effect = states
        provider._engine = engine
        return provider

    def configure_provider_request_payload(self, provider, payload):
        provider._comm.RequestContentProvider.side_effect = lambda: provider._on_control_received(payload)

    def test_fetch_online_uses_two_second_reconnect_timeout_by_default(self):
        provider = object.__new__(api_server.PyMobileCommProvider)
        provider._logger = self.make_null_logger("test_fetch_online_uses_two_second_reconnect_timeout_by_default")
        provider._lock = threading.Lock()
        observed = {}

        def ensure_connected(timeout_s, poll_interval_s, trace_id=None):
            observed["reconnect_timeout_s"] = timeout_s
            observed["poll_interval_s"] = poll_interval_s
            observed["trace_id"] = trace_id
            return True

        def request_provider(timeout_s=3.0):
            observed["provider_timeout_s"] = timeout_s
            return {"depth": "40"}

        provider.ensure_connected_for_online = ensure_connected
        provider._request_provider_locked = request_provider

        data = provider.fetch_online(trace_id="unit-trace")

        self.assertEqual(data, {"depth": "40"})
        self.assertEqual(observed["reconnect_timeout_s"], 2.0)
        self.assertEqual(observed["provider_timeout_s"], 3.0)
        self.assertEqual(observed["poll_interval_s"], 0.05)
        self.assertEqual(observed["trace_id"], "unit-trace")

    def test_fetch_online_exits_process_when_reconnect_still_disconnected(self):
        provider = self.make_provider_for_reconnect_tests([None, None])
        exit_codes = []
        original_exit = api_server.os._exit

        def fake_exit(exit_code):
            exit_codes.append(exit_code)
            raise SystemExit(exit_code)

        try:
            api_server.os._exit = fake_exit
            with self.assertRaises(SystemExit) as raised:
                provider.fetch_online(timeout_s=0.0, poll_interval_s=0.0, reconnect_timeout_s=0.0)
        finally:
            api_server.os._exit = original_exit

        provider._comm.RestartAdbServer.assert_called_once()
        provider._comm.Auto_Initialize.assert_called_once()
        provider._comm.RequestContentProvider.assert_not_called()
        self.assertEqual(raised.exception.code, 70)
        self.assertEqual(exit_codes, [70])

    def test_fetch_normalizes_focus_coordinates_from_callback_payload(self):
        provider = self.make_provider_for_reconnect_tests([make_state()])
        self.configure_provider_request_payload(
            provider,
            json.dumps(
                {
                    "depth": "40",
                    "focus_x": "434.85052",
                    "focus_y": "272.8398",
                }
            ),
        )

        data = provider.fetch(timeout_s=0.1)

        provider._comm.RequestContentProvider.assert_called_once()
        self.assertEqual(data["depth"], "40")
        self.assertEqual(data["focus_point"], "PointF(434.85052, 272.8398)")

    def test_fetch_extracts_json_from_wrapped_provider_callback_payload(self):
        provider = self.make_provider_for_reconnect_tests([make_state()])
        self.configure_provider_request_payload(
            provider,
            'provider={"focus_depth":"7.5","guankuan_a":"10.1","guankuan_b":"20.2","depth":"35","isLive":true,"mode":2,"focus_x":"111.25","focus_y":"222.5"} trailing text',
        )

        data = provider.fetch(timeout_s=0.1)

        provider._comm.RequestContentProvider.assert_called_once()
        self.assertEqual(data["focus_depth"], "7.5")
        self.assertEqual(data["guankuan_a"], "10.1")
        self.assertEqual(data["guankuan_b"], "20.2")
        self.assertEqual(data["depth"], "35")
        self.assertEqual(data["focus_point"], "PointF(111.25, 222.5)")

    def test_provider_callback_logs_raw_and_normalized_payload(self):
        logger, stream = self.make_stream_logger("test_provider_callback_logs_raw_and_normalized_payload")
        provider = self.make_provider_for_reconnect_tests([make_state()])
        provider._logger = logger
        self.configure_provider_request_payload(
            provider,
            'provider={"depth":"35","focus_x":"111.25","focus_y":"222.5"} trailing text',
        )

        data = provider.fetch(timeout_s=0.1)

        self.assertEqual(data["focus_point"], "PointF(111.25, 222.5)")
        log_text = stream.getvalue()
        self.assertIn("RequestContentProvider callback raw payload:", log_text)
        self.assertIn("RequestContentProvider callback normalized payload:", log_text)
        self.assertIn('"depth": "35"', log_text)
        self.assertIn('"focus_point": "PointF(111.25, 222.5)"', log_text)

    def test_fetch_raises_timeout_when_provider_callback_missing(self):
        provider = self.make_provider_for_reconnect_tests([make_state()])

        with self.assertRaisesRegex(TimeoutError, "RequestContentProvider timed out"):
            provider.fetch(timeout_s=0.0)

        provider._comm.RequestContentProvider.assert_called_once()

    def test_fetch_raises_on_invalid_provider_callback_json(self):
        provider = self.make_provider_for_reconnect_tests([make_state()])
        self.configure_provider_request_payload(provider, "{bad json}")

        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            provider.fetch(timeout_s=0.1)

        provider._comm.RequestContentProvider.assert_called_once()

    def test_fetch_online_reconnects_disconnected_state_then_fetches_after_success(self):
        provider = self.make_provider_for_reconnect_tests(
            [make_state(control=0, image=0), make_state(control=1, image=1)]
        )
        self.configure_provider_request_payload(provider, json.dumps({"depth": "40"}))

        data = provider.fetch_online(timeout_s=0.1, poll_interval_s=0.0)

        provider._comm.RestartAdbServer.assert_called_once()
        provider._comm.Auto_Initialize.assert_called_once()
        provider._comm.RequestContentProvider.assert_called_once()
        self.assertEqual(data, {"depth": "40"})

    def test_fetch_online_skips_reconnect_when_state_connected(self):
        provider = self.make_provider_for_reconnect_tests([make_state()])
        self.configure_provider_request_payload(provider, json.dumps({"depth": "41"}))

        data = provider.fetch_online(timeout_s=0.1, poll_interval_s=0.0)

        provider._comm.RestartAdbServer.assert_not_called()
        provider._comm.Auto_Initialize.assert_not_called()
        provider._comm.RequestContentProvider.assert_called_once()
        self.assertEqual(data, {"depth": "41"})

    def test_online_failed_reconnect_exits_before_returning_null_response(self):
        provider = self.make_provider_for_reconnect_tests([None, None])
        exit_codes = []
        original_exit = api_server.os._exit

        def fake_exit(exit_code):
            exit_codes.append(exit_code)
            raise SystemExit(exit_code)

        try:
            api_server.os._exit = fake_exit
            with self.assertRaises(SystemExit) as raised:
                api_server.handle_request(
                    'ONLINE;31415;{}',
                    provider_fetcher=lambda: provider.fetch_online(
                        timeout_s=0.0,
                        poll_interval_s=0.0,
                        reconnect_timeout_s=0.0,
                    ),
                )
        finally:
            api_server.os._exit = original_exit

        self.assertEqual(raised.exception.code, 70)
        self.assertEqual(exit_codes, [70])
        provider._comm.RequestContentProvider.assert_not_called()

    def test_fetch_online_logs_reconnect_timepoints(self):
        stream = StringIO()
        logger = logging.getLogger("test_fetch_online_logs_reconnect_timepoints")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        logger.addHandler(handler)

        provider = object.__new__(api_server.PyMobileCommProvider)
        provider._logger = logger
        provider._comm = Mock()
        provider._lock = threading.Lock()
        provider._request_state_lock = threading.Lock()
        provider._pending_provider_event = None
        provider._pending_provider_payload = None
        provider._pending_provider_error = None
        engine = Mock()
        engine.get_latest_state.side_effect = [make_state(control=0, image=0), make_state()]
        provider._engine = engine
        provider._comm.RequestContentProvider.side_effect = lambda: provider._on_control_received(
            json.dumps({"depth": "42"})
        )

        provider.fetch_online(timeout_s=0.1, poll_interval_s=0.0, trace_id="unit-trace")

        log_text = stream.getvalue()
        self.assertIn("step=device_connect_check_start", log_text)
        self.assertIn("step=device_reconnect_start", log_text)
        self.assertIn("step=device_reconnect_auto_initialize_completed", log_text)
        self.assertIn("step=device_reconnect_wait_completed", log_text)
        self.assertIn("step=provider_fetch_start", log_text)
        self.assertIn("step=provider_fetch_completed", log_text)


if __name__ == "__main__":
    unittest.main()
