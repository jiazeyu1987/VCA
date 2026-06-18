import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

import tools.session_timeline_analyzer as analyzer


def write_png(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (4, 3), color)
    image.save(path, format="PNG")


def create_sample_package(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_png(root / "frames" / "frame_000001_seq_000000007_offline_capture.png", (20, 30, 40))
        (root / "manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "session_id": "sample",
                    "point_id": 123,
                    "frame_count": 1,
                    "online_event_count": 1,
                    "package_status": "completed",
                }
            ),
            encoding="utf-8",
        )
        events = [
            {
                "schema_version": "1.0",
                "session_id": "sample",
                "event_type": "offline_start",
                "epoch_ms": 1000,
                "perf_counter_ns": 1_000_000,
                "wall_time_iso": "2026-06-18T10:00:00.000",
            },
            {
                "schema_version": "1.0",
                "session_id": "sample",
                "event_type": "offline_frame",
                "epoch_ms": 1010,
                "perf_counter_ns": 1_010_000,
                "wall_time_iso": "2026-06-18T10:00:00.010",
                "frame_id": "frame_000001",
                "frame_seq": 7,
                "path": "frames/frame_000001_seq_000000007_offline_capture.png",
            },
            {
                "schema_version": "1.0",
                "session_id": "sample",
                "event_type": "online_request",
                "epoch_ms": 1025,
                "perf_counter_ns": 1_025_000,
                "wall_time_iso": "2026-06-18T10:00:00.025",
                "trace_id": "trace-1",
                "server_duration_ms": 2.5,
            },
            {
                "schema_version": "1.0",
                "session_id": "sample",
                "event_type": "offline_end",
                "epoch_ms": 1100,
                "perf_counter_ns": 1_100_000,
                "wall_time_iso": "2026-06-18T10:00:00.100",
            },
        ]
        (root / "events.jsonl").write_text(
            "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
            encoding="utf-8",
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(root).as_posix())


class SessionTimelineAnalyzerTests(unittest.TestCase):
    def test_load_session_package_parses_manifest_events_and_frame_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_sample.zip"
            create_sample_package(package_path)

            package = analyzer.load_session_package(package_path)

            try:
                self.assertEqual(package.manifest["session_id"], "sample")
                self.assertEqual([event.event_type for event in package.events], [
                    "offline_start",
                    "offline_frame",
                    "online_request",
                    "offline_end",
                ])
                self.assertEqual(package.events[1].image_path, "frames/frame_000001_seq_000000007_offline_capture.png")
                image = package.open_image(package.events[1])
                self.assertEqual(image.size, (4, 3))
                self.assertEqual(image.getpixel((0, 0)), (20, 30, 40))
            finally:
                package.close()

    def test_selecting_online_event_uses_nearest_previous_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_sample.zip"
            create_sample_package(package_path)
            package = analyzer.load_session_package(package_path)

            try:
                selected = package.resolve_image_event(package.events[2])

                self.assertEqual(selected.event_type, "offline_frame")
                self.assertEqual(selected.frame_seq, 7)
            finally:
                package.close()

    def test_timeline_viewport_pan_zoom_and_hit_testing(self):
        viewport = analyzer.TimelineViewport(start_ns=1_000_000, end_ns=1_100_000, width=1000)

        viewport.zoom_at(0.5, 2.0)
        x_before = viewport.time_to_x(1_025_000)
        viewport.pan_pixels(100)
        x_after_pan = viewport.time_to_x(1_025_000)
        viewport.zoom_at(0.5, 2.0)
        x_after_zoom = viewport.time_to_x(1_025_000)

        self.assertLess(x_after_pan, x_before)
        self.assertNotEqual(x_after_zoom, x_after_pan)
        self.assertEqual(viewport.hit_test([1_000_000, 1_025_000, 1_100_000], viewport.time_to_x(1_025_000), tolerance_px=4), 1)

    def test_missing_required_package_file_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_bad.zip"
            with zipfile.ZipFile(package_path, "w") as archive:
                archive.writestr("manifest.json", "{}")

            with self.assertRaisesRegex(analyzer.SessionPackageError, "events.jsonl"):
                analyzer.load_session_package(package_path)


if __name__ == "__main__":
    unittest.main()
