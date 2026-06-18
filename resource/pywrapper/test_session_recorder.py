import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

import session_recorder


class SessionRecorderTests(unittest.TestCase):
    def make_config(self, output_dir: str, max_writer_queue: int = 16):
        return session_recorder.SessionRecorderConfig(
            enabled=True,
            output_dir=output_dir,
            frame_format="png",
            max_writer_queue=max_writer_queue,
            include_online_response=True,
            include_trace_json=True,
            package_on_finish=True,
        )

    def make_logger(self):
        logger = logging.getLogger("test_session_recorder")
        logger.handlers.clear()
        logger.propagate = False
        logger.addHandler(logging.NullHandler())
        return logger

    def read_zip_json(self, archive: zipfile.ZipFile, name: str):
        return json.loads(archive.read(name).decode("utf-8"))

    def test_records_complete_session_package_with_frames_results_trace_and_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = session_recorder.SessionDataRecorder(
                self.make_config(tmp),
                logger=self.make_logger(),
                id_factory=lambda point_id: f"20260618_102500_123_point_{point_id}_abcdef",
            )

            recorder.start_session(
                point_id=123,
                meta={"duration_s": 10.0, "is_save": True},
                server={"host": "127.0.0.1", "port": 30415},
            )
            recorder.record_frame(
                np.full((3, 4, 3), 20, dtype=np.uint8),
                frame_seq=7,
                frame_ts=1000.125,
                frame_index=1,
                source="offline_capture",
                tag="frame",
                metrics={"roi1_mean": 20.0},
            )
            recorder.record_online_request(
                trace_id="trace-1",
                request_started_perf_counter_ns=1_000_000,
                request_ended_perf_counter_ns=3_500_000,
                response_kind="online_success",
                response_summary={"Depth": 40, "isHIFU": False},
                latest_frame_seq=7,
            )
            recorder.mark_offline_stop_requested()
            recorder.record_offline_result(
                {
                    "success": True,
                    "info": "offline_stop_completed",
                    "point_id": 123,
                    "roi2_color": "green",
                }
            )

            package_path = recorder.finish_session()

            self.assertTrue(package_path.exists())
            self.assertFalse(Path(str(package_path).replace(".zip", ".partial")).exists())
            with zipfile.ZipFile(package_path) as archive:
                names = set(archive.namelist())
                self.assertIn("manifest.json", names)
                self.assertIn("events.jsonl", names)
                self.assertIn("results/offline_result.json", names)
                self.assertIn("results/online_000001.json", names)
                self.assertIn("trace.json", names)
                self.assertIn("checksums.json", names)
                frame_names = [name for name in names if name.startswith("frames/") and name.endswith(".png")]
                self.assertEqual(len(frame_names), 1)

                manifest = self.read_zip_json(archive, "manifest.json")
                self.assertEqual(manifest["schema_version"], "1.0")
                self.assertEqual(manifest["session_id"], "20260618_102500_123_point_123_abcdef")
                self.assertEqual(manifest["point_id"], 123)
                self.assertEqual(manifest["frame_count"], 1)
                self.assertEqual(manifest["online_event_count"], 1)
                self.assertEqual(manifest["result_count"], 2)
                self.assertEqual(manifest["package_status"], "completed")
                self.assertEqual(manifest["recording_config"]["frame_format"], "png")

                event_lines = archive.read("events.jsonl").decode("utf-8").splitlines()
                event_types = [json.loads(line)["event_type"] for line in event_lines]
                self.assertIn("offline_start", event_types)
                self.assertIn("offline_frame", event_types)
                self.assertIn("online_request", event_types)
                self.assertIn("offline_stop_requested", event_types)
                self.assertIn("offline_result", event_types)
                self.assertIn("offline_end", event_types)
                self.assertIn("package_finalized", event_types)

                online_result = self.read_zip_json(archive, "results/online_000001.json")
                self.assertEqual(online_result["Depth"], 40)
                offline_result = self.read_zip_json(archive, "results/offline_result.json")
                self.assertEqual(offline_result["roi2_color"], "green")

                trace = self.read_zip_json(archive, "trace.json")
                trace_names = [event["name"] for event in trace["traceEvents"]]
                self.assertIn("offline_session", trace_names)
                self.assertIn("offline_capture", trace_names)
                self.assertIn("offline_frame", trace_names)
                self.assertIn("online_request", trace_names)
                self.assertIn("package_finalize", trace_names)

                checksums = self.read_zip_json(archive, "checksums.json")
                self.assertIn("events.jsonl", checksums)
                self.assertIn(frame_names[0], checksums)

    def test_parse_session_recorder_config_requires_output_dir_when_enabled(self):
        with self.assertRaisesRegex(ValueError, "settings.session_recording.output_dir is required"):
            session_recorder.parse_session_recorder_config(
                {
                    "session_recording": {
                        "enabled": True,
                        "frame_format": "png",
                        "max_writer_queue": 16,
                        "include_online_response": True,
                        "include_trace_json": True,
                        "package_on_finish": True,
                    }
                }
            )

    def test_frame_write_failure_is_reported_during_finalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = session_recorder.SessionDataRecorder(
                self.make_config(tmp),
                logger=self.make_logger(),
                id_factory=lambda point_id: f"20260618_102500_123_point_{point_id}_abcdef",
            )
            recorder.start_session(point_id=123, meta={}, server={})

            with patch("session_recorder.write_png", side_effect=OSError("disk full")):
                recorder.record_frame(
                    np.full((3, 4, 3), 20, dtype=np.uint8),
                    frame_seq=7,
                    frame_ts=1000.125,
                    frame_index=1,
                    source="offline_capture",
                    tag="frame",
                    metrics={},
                )
                with self.assertRaisesRegex(OSError, "disk full"):
                    recorder.finish_session()


if __name__ == "__main__":
    unittest.main()
