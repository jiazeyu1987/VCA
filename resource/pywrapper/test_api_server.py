import json
import logging
import errno
from io import StringIO
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

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
                    "difference_threshold": 1.5,
                    "roi3_g1_g2_override": {"enabled": True, "g1_threshold": 97.0, "g2_threshold": 18.0, "use_peak_max": False},
                    "roi3_column_diff_override": {"enabled": True, "g1_threshold": 98.0, "threshold": 11.0, "use_peak_max": False},
                },
                "offline_tmp_frames": {"enabled": True, "dir": "D:/software_data/tmp"},
                "offline_stop_wait_timeout_seconds": 8.0,
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
        self.assertEqual(config.difference_threshold, 1.5)
        self.assertEqual(config.roi3_g1_g2_override["g1_threshold"], 97.0)
        self.assertEqual(config.roi3_column_diff_override["threshold"], 11.0)
        self.assertTrue(config.debug_save_enabled)
        self.assertEqual(config.debug_save_dir, "D:/software_data/tmp")
        self.assertEqual(config.stop_wait_timeout_seconds, 8.0)
        self.assertTrue(config.screenshot_test_enabled)

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

    def test_offline_requires_time_out_and_is_save_fields(self):
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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

    def test_offline_roi3_g1_g2_override_can_flip_red_to_green(self):
        before = np.full((200, 200, 3), 10, dtype=np.uint8)
        after = np.full((200, 200, 3), 200, dtype=np.uint8)
        after[99:101, 99:101] = 12
        frames = [
            api_server.FrameSnapshot(before, 1, 1.0),
            api_server.FrameSnapshot(after, 2, 2.0),
        ]
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(100, 100)"},
            frame_fetcher=lambda: frames.pop(0),
            config=api_server.OfflineConfig(
                peak_detect_enabled=True,
                roi2_extension_params={"left": 1, "right": 1, "top": 1, "bottom": 1},
                roi3_extension_params={"left": 50, "right": 50, "top": 50, "bottom": 50},
                difference_threshold=5.0,
                roi3_g1_g2_override={"enabled": True, "g1_threshold": 98.0, "g2_threshold": 20.0, "use_peak_max": False},
                roi3_column_diff_override={"enabled": False, "g1_threshold": 99.0, "threshold": 15.0, "use_peak_max": False},
            ),
            logger=self.make_null_logger("test_offline_roi3_g1_g2_override_can_flip_red_to_green"),
        )

        manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')
        stop = manager.handle('{"point_id": 123, "time_out": 100, "is_save": true}')

        self.assertEqual(stop["roi2_diff"], 2.0)
        self.assertEqual(stop["roi2_color"], "green")
        self.assertTrue(stop["roi3_override_applied"])
        self.assertEqual(stop["roi3_override_method"], "roi3_g1_g2")

    def test_offline_peak_selection_uses_peak_after_frame_not_stop_frame(self):
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 4, 4.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 13, dtype=np.uint8), 6, 6.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 14, dtype=np.uint8), 7, 7.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 200, dtype=np.uint8), 8, 8.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)"},
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
            logger=self.make_null_logger("test_offline_peak_selection_uses_peak_after_frame_not_stop_frame"),
        )

        start = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')
        self.assertEqual(start["info"], "offline_started")
        time.sleep(0.15)
        stop = manager.handle('{"point_id": 123, "time_out": 10, "is_save": true}')

        self.assertEqual(stop["info"], "offline_stop_completed")
        self.assertEqual(stop["roi2_after_mean"], 14.0)
        self.assertEqual(stop["roi2_color"], "red")

    def test_offline_switch_waits_for_previous_capture_done_before_new_start(self):
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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

    def test_offline_debug_save_flushes_buffered_frames_and_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 3, 3.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)"},
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

    def test_offline_peak_logs_threshold_and_after_selection(self):
        logger, stream = self.make_stream_logger("test_offline_peak_logs_threshold_and_after_selection")
        frames = self.SequenceFrameSource(
            [
                api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 3, 3.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
                api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
            ]
        )
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(20, 20)"},
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
        self.assertIn("OFFLINE diag peak_enter_high:", log_text)
        self.assertIn("OFFLINE diag peak_end_detected:", log_text)
        self.assertIn("OFFLINE diag after_selected:", log_text)
        self.assertIn('"after_method": "peak+1"', log_text)

    def test_offline_diff_image_contains_overlay_not_raw_positive_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((80, 80, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((80, 80, 3), 30, dtype=np.uint8), 2, 2.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(40, 40)"},
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

    def test_offline_output_logs_flush_and_output_paths(self):
        logger, stream = self.make_stream_logger("test_offline_output_logs_flush_and_output_paths")
        with tempfile.TemporaryDirectory() as tmp:
            frames = self.SequenceFrameSource(
                [
                    api_server.FrameSnapshot(np.full((40, 40, 3), 10, dtype=np.uint8), 1, 1.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 60, dtype=np.uint8), 2, 2.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 20, dtype=np.uint8), 3, 3.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 4, 4.0),
                    api_server.FrameSnapshot(np.full((40, 40, 3), 12, dtype=np.uint8), 5, 5.0),
                ]
            )
            manager = api_server.OfflineSessionManager(
                provider_fetcher=lambda: {"focus_point": "PointF(20, 20)"},
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
            self.assertIn("OFFLINE diag buffer_flush_begin:", log_text)
            self.assertIn("OFFLINE diag buffer_flush_completed:", log_text)
            self.assertIn("OFFLINE diag result_flag_written:", log_text)
            self.assertIn("OFFLINE diag final_outputs_saved:", log_text)
            self.assertIn('"meta_jsonl":', log_text)
            self.assertIn('"diff_path":', log_text)

    def test_offline_red_path_logs_decision_details(self):
        logger, stream = self.make_stream_logger("test_offline_red_path_logs_decision_details")
        frames = self.SequenceFrameSource([
            api_server.FrameSnapshot(np.full((20, 20, 3), 10, dtype=np.uint8), 1, 1.0),
            api_server.FrameSnapshot(np.full((20, 20, 3), 12, dtype=np.uint8), 2, 2.0),
        ])
        manager = api_server.OfflineSessionManager(
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
                provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
            provider_fetcher=lambda: {"focus_point": "PointF(10, 10)"},
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
                provider_fetcher=lambda: {"focus_point": "PointF(40, 40)"},
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

    def make_provider_for_reconnect_tests(self, states):
        provider = object.__new__(api_server.PyMobileCommProvider)
        provider._logger = self.make_null_logger("provider_reconnect_test")
        provider._comm = Mock()
        provider._lock = threading.Lock()
        engine = Mock()
        engine.get_latest_state.side_effect = states
        provider._engine = engine
        return provider

    def test_fetch_online_reconnects_when_state_missing_and_returns_empty_provider_after_timeout(self):
        provider = self.make_provider_for_reconnect_tests([None, None])

        data = provider.fetch_online(timeout_s=0.0, poll_interval_s=0.0)

        provider._comm.RestartAdbServer.assert_called_once()
        provider._comm.Auto_Initialize.assert_called_once()
        provider._comm.GetContentProvider.assert_not_called()
        self.assertEqual(data, {})

    def test_fetch_online_reconnects_disconnected_state_then_fetches_after_success(self):
        provider = self.make_provider_for_reconnect_tests(
            [make_state(control=0, image=0), make_state(control=1, image=1)]
        )
        provider._comm.GetContentProvider.return_value = {"depth": "40"}

        data = provider.fetch_online(timeout_s=0.1, poll_interval_s=0.0)

        provider._comm.RestartAdbServer.assert_called_once()
        provider._comm.Auto_Initialize.assert_called_once()
        provider._comm.GetContentProvider.assert_called_once()
        self.assertEqual(data, {"depth": "40"})

    def test_fetch_online_skips_reconnect_when_state_connected(self):
        provider = self.make_provider_for_reconnect_tests([make_state()])
        provider._comm.GetContentProvider.return_value = {"depth": "41"}

        data = provider.fetch_online(timeout_s=0.1, poll_interval_s=0.0)

        provider._comm.RestartAdbServer.assert_not_called()
        provider._comm.Auto_Initialize.assert_not_called()
        provider._comm.GetContentProvider.assert_called_once()
        self.assertEqual(data, {"depth": "41"})

    def test_online_failed_reconnect_keeps_online_response_shape(self):
        provider = self.make_provider_for_reconnect_tests([None, None])

        response = api_server.handle_request(
            'ONLINE;31415;{}',
            provider_fetcher=lambda: provider.fetch_online(timeout_s=0.0, poll_interval_s=0.0),
        )

        payload = json.loads(response)
        self.assertEqual(
            payload,
            {
                "SkinDepth": None,
                "A": None,
                "B": None,
                "Alpha": 0,
                "Depth": None,
                "IsFreeze": None,
                "isHIFU": False,
                "FocusPoint": None,
            },
        )
        provider._comm.GetContentProvider.assert_not_called()

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
        engine = Mock()
        engine.get_latest_state.side_effect = [make_state(control=0, image=0), make_state()]
        provider._engine = engine
        provider._comm.GetContentProvider.return_value = {"depth": "42"}

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
