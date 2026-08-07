import json
from io import BytesIO
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from PIL import Image

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

            recording_session_id = recorder.start_session(
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
                session_id=recording_session_id,
            )
            recorder.record_online_request(
                trace_id="trace-1",
                request_started_perf_counter_ns=1_000_000,
                request_ended_perf_counter_ns=3_500_000,
                response_kind="online_success",
                response_summary={"Depth": 40, "isHIFU": False},
                latest_frame_seq=7,
            )
            recorder.mark_offline_stop_requested(session_id=recording_session_id)
            recorder.record_offline_result(
                {
                    "success": True,
                    "info": "offline_stop_completed",
                    "point_id": 123,
                    "roi2_color": "green",
                },
                session_id=recording_session_id,
            )

            recorder.detach_session(session_id=recording_session_id)
            package_path = recorder.finish_session(session_id=recording_session_id)

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

    def test_stopping_session_can_finalize_while_next_session_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = session_recorder.SessionDataRecorder(
                self.make_config(tmp),
                logger=self.make_logger(),
                id_factory=lambda point_id: f"20260618_102500_123_point_{point_id}_abcdef",
            )
            first_session_id = recorder.start_session(point_id=123, meta={}, server={})
            recorder.record_frame(
                np.full((3, 4, 3), 20, dtype=np.uint8),
                frame_seq=7,
                frame_ts=1000.125,
                frame_index=1,
                source="offline_capture",
                tag="frame",
                metrics={},
                session_id=first_session_id,
            )
            recorder.mark_offline_stop_requested(session_id=first_session_id)
            recorder.detach_session(session_id=first_session_id)

            second_session_id = recorder.start_session(point_id=124, meta={}, server={})
            recorder.record_frame(
                np.full((3, 4, 3), 40, dtype=np.uint8),
                frame_seq=8,
                frame_ts=1001.125,
                frame_index=1,
                source="offline_capture",
                tag="frame",
                metrics={},
                session_id=second_session_id,
            )
            recorder.mark_offline_stop_requested(session_id=second_session_id)
            recorder.record_offline_result(
                {"success": True, "point_id": 123},
                session_id=first_session_id,
            )
            recorder.record_offline_result(
                {"success": True, "point_id": 124},
                session_id=second_session_id,
            )

            first_package = recorder.finish_session(session_id=first_session_id)
            self.assertTrue(recorder.is_active())
            second_package = recorder.finish_session(session_id=second_session_id)

            self.assertTrue(first_package.exists())
            self.assertTrue(second_package.exists())
            with zipfile.ZipFile(first_package) as archive:
                first_manifest = self.read_zip_json(archive, "manifest.json")
                self.assertEqual(first_manifest["point_id"], 123)
                self.assertEqual(first_manifest["frame_count"], 1)
                first_result = self.read_zip_json(archive, "results/offline_result.json")
                self.assertEqual(first_result["point_id"], 123)
                first_frame_name = next(name for name in archive.namelist() if name.startswith("frames/"))
                first_frame = np.asarray(Image.open(BytesIO(archive.read(first_frame_name))))
                self.assertTrue(np.all(first_frame == 20))
            with zipfile.ZipFile(second_package) as archive:
                second_manifest = self.read_zip_json(archive, "manifest.json")
                self.assertEqual(second_manifest["point_id"], 124)
                self.assertEqual(second_manifest["frame_count"], 1)
                second_result = self.read_zip_json(archive, "results/offline_result.json")
                self.assertEqual(second_result["point_id"], 124)
                second_frame_name = next(name for name in archive.namelist() if name.startswith("frames/"))
                second_frame = np.asarray(Image.open(BytesIO(archive.read(second_frame_name))))
                self.assertTrue(np.all(second_frame == 40))

    def test_previous_session_finalize_failure_does_not_clear_active_next_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = session_recorder.SessionDataRecorder(
                self.make_config(tmp),
                logger=self.make_logger(),
                id_factory=lambda point_id: f"20260618_102500_123_point_{point_id}_abcdef",
            )
            first_session_id = recorder.start_session(point_id=123, meta={}, server={})
            recorder.mark_offline_stop_requested(session_id=first_session_id)
            recorder.detach_session(session_id=first_session_id)
            second_session_id = recorder.start_session(point_id=124, meta={}, server={})
            recorder.mark_offline_stop_requested(session_id=second_session_id)

            original_write_zip_package = recorder._write_zip_package

            def fail_first_package(session):
                if session.session_id == first_session_id:
                    raise OSError("first package disk failure")
                return original_write_zip_package(session)

            with patch.object(recorder, "_write_zip_package", side_effect=fail_first_package):
                with self.assertRaisesRegex(OSError, "first package disk failure"):
                    recorder.finish_session(session_id=first_session_id)
                self.assertTrue(recorder.is_active())
                second_package = recorder.finish_session(session_id=second_session_id)

            self.assertTrue(second_package.exists())

    def test_frame_write_failure_is_reported_during_finalize(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = session_recorder.SessionDataRecorder(
                self.make_config(tmp),
                logger=self.make_logger(),
                id_factory=lambda point_id: f"20260618_102500_123_point_{point_id}_abcdef",
            )
            recording_session_id = recorder.start_session(point_id=123, meta={}, server={})

            with patch("session_recorder.write_png", side_effect=OSError("disk full")):
                recorder.record_frame(
                    np.full((3, 4, 3), 20, dtype=np.uint8),
                    frame_seq=7,
                    frame_ts=1000.125,
                    frame_index=1,
                    source="offline_capture",
                    tag="frame",
                    metrics={},
                    session_id=recording_session_id,
                )
                with self.assertRaisesRegex(OSError, "disk full"):
                    recorder.finish_session(session_id=recording_session_id)


if __name__ == "__main__":
    unittest.main()
