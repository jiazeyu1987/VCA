import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = WORKSPACE_ROOT / "tools" / "offline_screenshot_probe.py"


def load_probe_module():
    spec = importlib.util.spec_from_file_location("offline_screenshot_probe", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class OfflineScreenshotProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.probe = load_probe_module()

    def test_module_exists(self):
        self.assertTrue(MODULE_PATH.exists(), MODULE_PATH)

    def test_build_request_text_formats_shutdown_without_payload(self):
        self.assertEqual(
            self.probe.build_request_text("SHUTDOWN", "31415", None),
            "SHUTDOWN;31415\n",
        )

    def test_build_request_text_formats_online_with_json_payload(self):
        self.assertEqual(
            self.probe.build_request_text("ONLINE", "31415", {}),
            'ONLINE;31415;{}\n',
        )

    def test_build_default_fixed_provider_data_matches_raw_provider_shape(self):
        payload = self.probe.build_default_fixed_provider_data()

        self.assertEqual(
            sorted(payload.keys()),
            sorted(["focus_depth", "guankuan_a", "guankuan_b", "depth", "focus_point", "isLive", "mode", "Alpha"]),
        )
        self.assertTrue(payload["isLive"])

    def test_argument_parser_accepts_no_device_fixed_data_mode(self):
        parser = self.probe.build_argument_parser()

        args = parser.parse_args(["--runtime-mode", "no_device_fixed_data"])

        self.assertEqual(args.runtime_mode, "no_device_fixed_data")

    def test_scan_screenshot_runtime_wiring_reports_false_when_no_tokens_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_server.py"
            path.write_text("print('image_matrix only')\n", encoding="utf-8")

            result = self.probe.scan_screenshot_runtime_wiring(path)

        self.assertFalse(result["screenshot_flag_wired"])
        self.assertEqual(result["matched_tokens"], [])

    def test_scan_screenshot_runtime_wiring_reports_true_when_tokens_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_server.py"
            path.write_text("offline_screenshot_test = True\npyautogui.screenshot()\n", encoding="utf-8")

            result = self.probe.scan_screenshot_runtime_wiring(path)

        self.assertTrue(result["screenshot_flag_wired"])
        self.assertIn("offline_screenshot_test", result["matched_tokens"])
        self.assertIn("pyautogui", result["matched_tokens"])

    def test_build_probe_settings_enables_flag_and_redirects_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp)
            base = {
                "offline_screenshot_test": {"enabled": False},
                "offline_tmp_frames": {"enabled": False, "dir": "D:/software_data/tmp", "max_buffer_frames": 2500},
            }

            updated = self.probe.build_probe_settings(base, output_root)

        self.assertTrue(updated["offline_screenshot_test"]["enabled"])
        self.assertEqual(updated["offline_tmp_frames"]["dir"], str((output_root / "offline_tmp_frames").as_posix()))
        self.assertEqual(updated["image_output_dir"], str((output_root / "image_output").as_posix()))
        self.assertEqual(updated["result_flag_path"], str((output_root / "result_flag.txt").as_posix()))
        self.assertIsNone(updated["db_root_dir"])

    def test_ensure_port_available_succeeds_for_bindable_port(self):
        self.probe.ensure_port_available("127.0.0.1", 30415, timeout_s=0.2)

    def test_summarize_online_records_marks_missing_second_windows(self):
        records = [
            self.probe.OnlineProbeRecord(window_index=0, start_ts=10.0, end_ts=10.1, latency_ms=100.0, parsed=True, timed_out=False, empty_fields=[]),
            self.probe.OnlineProbeRecord(window_index=2, start_ts=12.0, end_ts=12.2, latency_ms=200.0, parsed=True, timed_out=False, empty_fields=["Depth"]),
            self.probe.OnlineProbeRecord(window_index=3, start_ts=13.0, end_ts=15.0, latency_ms=None, parsed=False, timed_out=True, empty_fields=[]),
        ]

        summary = self.probe.summarize_online_records(records, expected_window_count=4)

        self.assertEqual(summary["online_probe_count"], 3)
        self.assertEqual(summary["online_success_count"], 2)
        self.assertEqual(summary["online_timeout_count"], 1)
        self.assertEqual(summary["online_empty_field_count"], 1)
        self.assertEqual(summary["online_missed_second_windows"], [1, 3])
        self.assertEqual(summary["online_latency_ms"]["min"], 100.0)
        self.assertEqual(summary["online_latency_ms"]["max"], 200.0)

    def test_classify_runtime_evidence_ignores_image_matrix_outputs_as_screenshots(self):
        log_text = "\n".join(
            [
                'INFO:OFFLINE diag handle: {"capture_source": "image_matrix"}',
                'INFO:OFFLINE diag stop_decision: {"capture_source": "image_matrix"}',
            ]
        )
        created_files = [
            "ocrlog/pywrapper_api_server.log",
            "image_output/2026_before.png",
            "image_output/2026_after.png",
            "image_output/2026_diff.png",
        ]

        result = self.probe.classify_runtime_evidence(log_text, created_files)

        self.assertEqual(result["screenshot_event_count"], 0)
        self.assertEqual(result["capture_sources_seen"], ["image_matrix"])

    def test_classify_runtime_evidence_counts_screenshot_specific_markers(self):
        log_text = "\n".join(
            [
                "INFO:screenshot region=(0,0,100,100)",
                'INFO:OFFLINE diag handle: {"capture_source": "screenshot"}',
            ]
        )
        created_files = ["captures/session_screenshot_0001.png"]

        result = self.probe.classify_runtime_evidence(log_text, created_files)

        self.assertGreaterEqual(result["screenshot_event_count"], 2)
        self.assertIn("screenshot", result["capture_sources_seen"])

    def test_classify_runtime_evidence_counts_capture_source_screenshot_even_without_filename_hint(self):
        log_text = 'INFO:OFFLINE diag handle: {"capture_source": "screenshot"}'

        result = self.probe.classify_runtime_evidence(log_text, [])

        self.assertGreaterEqual(result["screenshot_event_count"], 1)
        self.assertEqual(result["capture_sources_seen"], ["screenshot"])

    def test_probe_online_once_marks_timeout_when_recv_times_out(self):
        original_send = self.probe.send_tcp_request
        try:
            self.probe.send_tcp_request = lambda *args, **kwargs: (None, "", True)
            record = self.probe.probe_online_once("127.0.0.1", 30415, "31415", 1.0, base_ts=time.time(), interval_s=1.0)
        finally:
            self.probe.send_tcp_request = original_send

        self.assertFalse(record.parsed)
        self.assertTrue(record.timed_out)

    def test_build_final_conclusion_calls_out_missing_screenshot_path(self):
        report = {
            "screenshot_event_count": 0,
            "capture_sources_seen": ["image_matrix"],
            "screenshot_config_enabled": True,
            "screenshot_flag_wired": False,
            "online_missed_second_windows": [],
            "online_success_count": 15,
            "online_probe_count": 15,
        }

        conclusion = self.probe.build_final_conclusion(report)

        self.assertIn("did not observe a screenshot path", conclusion)
        self.assertIn("had no explicit effect", conclusion)
        self.assertIn("ONLINE delivered at least one parseable response per second", conclusion)

    def test_build_final_conclusion_keeps_negative_screenshot_result_in_no_device_mode(self):
        report = {
            "runtime_mode": "no_device_fixed_data",
            "screenshot_event_count": 0,
            "capture_sources_seen": ["image_matrix"],
            "screenshot_config_enabled": True,
            "screenshot_flag_wired": False,
            "online_missed_second_windows": [1],
            "online_success_count": 4,
            "online_probe_count": 4,
        }

        conclusion = self.probe.build_final_conclusion(report)

        self.assertIn("screenshot", conclusion)
        self.assertIn("ONLINE missed second windows", conclusion)

    def test_write_report_files_emits_json_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            report = {"final_conclusion": "ok", "online_probe_count": 1}

            paths = self.probe.write_report_files(output_dir, report)

            self.assertTrue(Path(paths["json_report"]).exists())
            self.assertTrue(Path(paths["summary_report"]).exists())
            data = json.loads(Path(paths["json_report"]).read_text(encoding="utf-8"))
            self.assertEqual(data["online_probe_count"], 1)
            summary_text = Path(paths["summary_report"]).read_text(encoding="utf-8")
            self.assertIn("final_conclusion", summary_text)


if __name__ == "__main__":
    unittest.main()
