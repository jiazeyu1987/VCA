import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import tools.session_timeline_analyzer as analyzer


def write_png(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (4, 3), color)
    image.save(path, format="PNG")


def create_sample_package_directory(root: Path) -> None:
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


def create_sample_package(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_sample_package_directory(root)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(root).as_posix())


def create_multiframe_package_directory(root: Path) -> None:
    for index, color in enumerate(((20, 30, 40), (50, 60, 70), (80, 90, 100)), start=1):
        write_png(root / "frames" / f"frame_{index:06d}_seq_{index:09d}_offline_capture.png", color)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "session_id": "multiframe",
                "point_id": 456,
                "frame_count": 3,
                "online_event_count": 0,
                "package_status": "completed",
            }
        ),
        encoding="utf-8",
    )
    events = [
        {
            "schema_version": "1.0",
            "session_id": "multiframe",
            "event_type": "offline_start",
            "epoch_ms": 1000,
            "perf_counter_ns": 1_000_000,
            "wall_time_iso": "2026-06-18T10:00:00.000",
        },
        {
            "schema_version": "1.0",
            "session_id": "multiframe",
            "event_type": "offline_frame",
            "epoch_ms": 1010,
            "perf_counter_ns": 1_010_000,
            "wall_time_iso": "2026-06-18T10:00:00.010",
            "frame_id": "frame_000001",
            "frame_seq": 1,
            "path": "frames/frame_000001_seq_000000001_offline_capture.png",
        },
        {
            "schema_version": "1.0",
            "session_id": "multiframe",
            "event_type": "offline_frame",
            "epoch_ms": 1040,
            "perf_counter_ns": 1_040_000,
            "wall_time_iso": "2026-06-18T10:00:00.040",
            "frame_id": "frame_000002",
            "frame_seq": 2,
            "path": "frames/frame_000002_seq_000000002_offline_capture.png",
        },
        {
            "schema_version": "1.0",
            "session_id": "multiframe",
            "event_type": "offline_frame",
            "epoch_ms": 1090,
            "perf_counter_ns": 1_090_000,
            "wall_time_iso": "2026-06-18T10:00:00.090",
            "frame_id": "frame_000003",
            "frame_seq": 3,
            "path": "frames/frame_000003_seq_000000003_offline_capture.png",
        },
        {
            "schema_version": "1.0",
            "session_id": "multiframe",
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


def create_multiframe_package(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_multiframe_package_directory(root)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(root).as_posix())


def create_stitched_package_directory(
    root: Path,
    *,
    session_id: str,
    point_id: int,
    start_epoch_ms: int,
    frame_times_ms: list[int],
) -> None:
    for index, offset_ms in enumerate(frame_times_ms, start=1):
        write_png(root / "frames" / f"frame_{index:06d}_seq_{index:09d}_offline_capture.png", (20 * index, 30, 40))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "session_id": session_id,
                "point_id": point_id,
                "frame_count": len(frame_times_ms),
                "online_event_count": 0,
                "package_status": "completed",
            }
        ),
        encoding="utf-8",
    )
    start_perf_ns = start_epoch_ms * 1_000_000
    events = [
        {
            "schema_version": "1.0",
            "session_id": session_id,
            "event_type": "offline_start",
            "epoch_ms": start_epoch_ms,
            "perf_counter_ns": start_perf_ns,
            "wall_time_iso": "2026-06-18T10:00:00.000",
        }
    ]
    for index, offset_ms in enumerate(frame_times_ms, start=1):
        epoch_ms = start_epoch_ms + offset_ms
        perf_ns = epoch_ms * 1_000_000
        events.append(
            {
                "schema_version": "1.0",
                "session_id": session_id,
                "event_type": "offline_frame",
                "epoch_ms": epoch_ms,
                "perf_counter_ns": perf_ns,
                "wall_time_iso": "2026-06-18T10:00:00.000",
                "frame_id": f"frame_{index:06d}",
                "frame_seq": index,
                "path": f"frames/frame_{index:06d}_seq_{index:09d}_offline_capture.png",
            }
        )
    end_epoch_ms = start_epoch_ms + (frame_times_ms[-1] if frame_times_ms else 0) + 10
    events.append(
        {
            "schema_version": "1.0",
            "session_id": session_id,
            "event_type": "offline_end",
            "epoch_ms": end_epoch_ms,
            "perf_counter_ns": end_epoch_ms * 1_000_000,
            "wall_time_iso": "2026-06-18T10:00:00.000",
        }
    )
    (root / "events.jsonl").write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )


def create_stitched_package(
    path: Path,
    *,
    session_id: str,
    point_id: int,
    start_epoch_ms: int,
    frame_times_ms: list[int],
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        create_stitched_package_directory(
            root,
            session_id=session_id,
            point_id=point_id,
            start_epoch_ms=start_epoch_ms,
            frame_times_ms=frame_times_ms,
        )
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in root.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(root).as_posix())


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.after_cancel_calls = []
        self.config_calls = []

    def after(self, delay_ms, callback, *args):
        self.after_calls.append((delay_ms, callback, args))
        return "after-id"

    def after_cancel(self, after_id):
        self.after_cancel_calls.append(after_id)

    def configure(self, **kwargs):
        self.config_calls.append(kwargs)


class FakeVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


class FakeButton:
    def __init__(self):
        self.config = {}
        self.grid_calls = []

    def configure(self, **kwargs):
        self.config.update(kwargs)

    def grid(self, *args, **kwargs):
        self.grid_calls.append((args, kwargs))


class FakeFrame:
    def __init__(self, *args, **kwargs):
        self.grid_calls = []
        self.columnconfigure_calls = []
        self.rowconfigure_calls = []

    def grid(self, *args, **kwargs):
        self.grid_calls.append((args, kwargs))

    def columnconfigure(self, *args, **kwargs):
        self.columnconfigure_calls.append((args, kwargs))

    def rowconfigure(self, *args, **kwargs):
        self.rowconfigure_calls.append((args, kwargs))


class FakeMenu:
    def __init__(self):
        self.commands = []
        self.cascades = []

    def add_command(self, **kwargs):
        self.commands.append(kwargs)

    def add_cascade(self, **kwargs):
        self.cascades.append(kwargs)


class FakeTimeline:
    def __init__(self):
        self.items = []
        self.width = 1000

    def delete(self, *args):
        self.items.append(("delete", args))

    def create_text(self, *args, **kwargs):
        self.items.append(("create_text", args, kwargs))
        return len(self.items)

    def create_line(self, *args, **kwargs):
        self.items.append(("create_line", args, kwargs))
        return len(self.items)

    def create_oval(self, *args, **kwargs):
        self.items.append(("create_oval", args, kwargs))
        return len(self.items)

    def winfo_width(self):
        return self.width


class FakeTreeview:
    def __init__(self):
        self.rows = {}
        self.selection_value = ()
        self.selection_callback = None

    def delete(self, *items):
        if not items:
            self.rows.clear()
            return
        for item in items:
            self.rows.pop(item, None)

    def get_children(self):
        return tuple(self.rows.keys())

    def insert(self, parent, index, iid=None, values=()):
        row_id = iid if iid is not None else str(len(self.rows))
        self.rows[row_id] = values
        return row_id

    def selection(self):
        return self.selection_value

    def selection_set(self, item):
        self.selection_value = (item,)
        if self.selection_callback is not None:
            self.selection_callback()

    def exists(self, item):
        return item in self.rows

    def see(self, item):
        return None


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

    def test_load_session_package_accepts_extracted_package_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp) / "session_sample"
            package_dir.mkdir()
            create_sample_package_directory(package_dir)

            package = analyzer.load_session_package(package_dir)

            try:
                self.assertEqual(package.manifest["session_id"], "sample")
                self.assertEqual(package.package_path, package_dir)
                self.assertEqual(package.open_image(package.events[1]).size, (4, 3))
            finally:
                package.close()

    def test_session_package_exposes_playback_frames_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_sample.zip"
            create_sample_package(package_path)
            package = analyzer.load_session_package(package_path)

            try:
                self.assertEqual([event.event_type for event in package.playback_frames], ["offline_frame"])
                self.assertEqual(package.playback_frames[0].frame_seq, 7)
            finally:
                package.close()

    def test_session_package_exposes_only_start_end_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_sample.zip"
            create_sample_package(package_path)
            package = analyzer.load_session_package(package_path)

            try:
                self.assertEqual(
                    [(marker.event_type, marker.user_marker_label) for marker in package.playback_markers],
                    [("offline_start", "offline start"), ("offline_end", "offline end")],
                )
            finally:
                package.close()

    def test_session_package_maps_playback_time_to_nearest_frame_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_multiframe.zip"
            create_multiframe_package(package_path)
            package = analyzer.load_session_package(package_path)

            try:
                self.assertEqual(package.playback_frame_index_for_time(1_010_000), 0)
                self.assertEqual(package.playback_frame_index_for_time(1_025_000), 0)
                self.assertEqual(package.playback_frame_index_for_time(1_040_000), 1)
                self.assertEqual(package.playback_frame_index_for_time(1_070_000), 1)
                self.assertEqual(package.playback_frame_index_for_time(1_095_000), 2)
            finally:
                package.close()

    def test_scan_session_directory_builds_stitched_timeline_in_timestamp_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_stitched_package(
                root / "session_later.zip",
                session_id="later",
                point_id=2,
                start_epoch_ms=3000,
                frame_times_ms=[0, 20],
            )
            create_stitched_package(
                root / "session_earlier.zip",
                session_id="earlier",
                point_id=1,
                start_epoch_ms=1000,
                frame_times_ms=[0, 50],
            )

            timeline = analyzer.build_stitched_timeline(root)

            self.assertEqual(
                [frame.session_id for frame in timeline.frames],
                ["earlier", "earlier", "later", "later"],
            )
            self.assertEqual(
                [marker.event_type for marker in timeline.markers],
                ["offline_start", "offline_end", "offline_start", "offline_end"],
            )

    def test_stitched_timeline_uses_real_frame_delay_between_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_stitched_package(
                root / "session_one.zip",
                session_id="one",
                point_id=1,
                start_epoch_ms=1000,
                frame_times_ms=[0, 30],
            )
            create_stitched_package(
                root / "session_two.zip",
                session_id="two",
                point_id=2,
                start_epoch_ms=1100,
                frame_times_ms=[0],
            )

            timeline = analyzer.build_stitched_timeline(root)

            self.assertEqual(timeline.frame_delay_ms(0), 30)
            self.assertEqual(timeline.frame_delay_ms(1), 70)
            self.assertEqual(timeline.frame_delay_ms(2), 0)

    def test_initialize_playback_starts_from_first_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            package_path = Path(tmp) / "session_multiframe.zip"
            create_multiframe_package(package_path)
            timeline = analyzer.build_stitched_timeline(tmp)
            app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
            app.playback_timeline = timeline
            app.current_playback_frame_index = None

            with patch.object(app, "display_playback_frame") as display_playback_frame:
                app.initialize_playback()

            display_playback_frame.assert_called_once_with(0)

    def test_build_menu_configures_menu_bar_on_root(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        app.root = FakeRoot()
        app.menu_bar = None

        with patch.object(analyzer.tk, "Menu") as menu_class:
            menu_bar = FakeMenu()
            file_menu = FakeMenu()
            menu_class.side_effect = [menu_bar, file_menu]

            app._build_menu()

        self.assertEqual(menu_class.call_count, 2)
        self.assertEqual(app.root.config_calls[-1], {"menu": menu_bar})
        self.assertIs(app.menu_bar, menu_bar)
        self.assertEqual(file_menu.commands[0]["label"], "选择基础目录")

    def test_choose_base_directory_menu_action_reuses_session_root_flow(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)

        with patch.object(app, "choose_session_root") as choose_session_root:
            app.choose_base_directory()

        choose_session_root.assert_called_once_with()

    def test_schedule_playback_tick_uses_stitched_frame_delay(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        app.root = FakeRoot()
        app.playback_timeline = type(
            "FakePlaybackTimeline",
            (),
            {"frame_delay_ms": lambda _self, index: 125},
        )()
        app.current_playback_frame_index = 0
        app.playback_speed = 1.0

        app._schedule_playback_tick()

        self.assertEqual(len(app.root.after_calls), 1)
        delay_ms, callback, args = app.root.after_calls[0]
        self.assertEqual(delay_ms, 125)
        self.assertEqual(callback, app._playback_tick)
        self.assertEqual(args, ())

    def test_schedule_playback_tick_applies_speed_multiplier(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        app.root = FakeRoot()
        app.playback_timeline = type(
            "FakePlaybackTimeline",
            (),
            {"frame_delay_ms": lambda _self, index: 120},
        )()
        app.current_playback_frame_index = 0
        app.playback_speed = 2.0

        app._schedule_playback_tick()

        delay_ms, _, _ = app.root.after_calls[0]
        self.assertEqual(delay_ms, 60)

    def test_set_playback_speed_updates_speed_var_and_stops_playback(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        app.playback_speed = 1.0
        app.speed_var = FakeVar()

        with patch.object(app, "stop_playback") as stop_playback:
            app.set_playback_speed(4.0)

        self.assertEqual(app.playback_speed, 4.0)
        self.assertEqual(app.speed_var.value, "4.0x")
        stop_playback.assert_called_once()

    def test_draw_timeline_renders_timestamp_tick_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_stitched_package(
                root / "session_ticks.zip",
                session_id="ticks",
                point_id=1,
                start_epoch_ms=1_000,
                frame_times_ms=[0, 100, 200],
            )
            timeline_model = analyzer.build_stitched_timeline(root)
            app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
            app.timeline = FakeTimeline()
            app.playback_timeline = timeline_model
            app.viewport = analyzer.TimelineViewport(timeline_model.start_ns, timeline_model.end_ns, 1000)
            app.playback_time_var = FakeVar()
            app.playback_time_var.set("1 / 3")
            app.current_playback_frame_index = 0

            app.draw_timeline()

            text_values = [
                item[2].get("text")
                for item in app.timeline.items
                if len(item) == 3 and item[0] == "create_text"
            ]
            self.assertTrue(any(isinstance(value, str) and ":" in value for value in text_values))

    def test_timeline_mousewheel_zoom_reduces_viewport_span(self):
        viewport = analyzer.TimelineViewport(start_ns=1_000_000, end_ns=1_100_000, width=1000)
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        app.playback_timeline = type("FakePlaybackTimeline", (), {"start_ns": 1_000_000, "end_ns": 1_100_000, "frames": [object()]})()
        app.viewport = viewport
        app.timeline = FakeTimeline()

        with patch.object(app, "draw_timeline") as draw_timeline:
            app.on_timeline_mousewheel(type("Event", (), {"delta": 120, "x": 500})())

        self.assertLess(app.viewport.span_ns, 100_000)
        draw_timeline.assert_called_once()

    def test_build_controls_creates_play_pause_and_speed_buttons(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        parent = FakeFrame()
        app.speed_var = FakeVar()
        app.speed_var.set("1.0x")

        button_texts = []

        def fake_button(_parent, text, command):
            button_texts.append(text)
            return FakeButton()

        with patch.object(analyzer.ttk, "Frame", side_effect=lambda *args, **kwargs: FakeFrame()):
            with patch.object(analyzer.ttk, "Button", side_effect=fake_button):
                with patch.object(analyzer.ttk, "Label", side_effect=lambda *args, **kwargs: FakeButton()):
                    app._build_controls(parent)

        self.assertIn("Play", button_texts)
        self.assertIn("Pause", button_texts)
        self.assertIn("1.0x", button_texts)

    def test_display_playback_frame_no_longer_requires_details_or_package_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_stitched_package(
                root / "session_only.zip",
                session_id="only",
                point_id=1,
                start_epoch_ms=1000,
                frame_times_ms=[0, 40],
            )
            timeline = analyzer.build_stitched_timeline(root)
            app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
            app.playback_timeline = timeline
            app.current_playback_frame_index = None
            app.playback_time_var = FakeVar()
            app.image_var = FakeVar()
            app.status_var = FakeVar()
            app.preview_label = type("FakeLabel", (), {"configure": lambda *args, **kwargs: None})()
            app.photo = None
            app.timeline = FakeTimeline()
            app.package = None
            app.selected_event = None

            with patch.object(app, "show_stitched_frame") as show_stitched_frame:
                with patch.object(app, "draw_timeline"):
                    app.display_playback_frame(0)

            show_stitched_frame.assert_called_once()
            self.assertEqual(app.playback_time_var.value, "1 / 2")

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

    def test_load_path_starts_background_worker_without_blocking_ui_callback(self):
        app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
        app.root = FakeRoot()
        app.package = None
        app.playback_timeline = None
        app.viewport = None
        app.status_var = FakeVar()
        app.image_var = FakeVar()
        app.timeline = FakeTimeline()
        app.open_root_button = FakeButton()
        app.open_folder_button = FakeButton()
        app.open_zip_button = FakeButton()
        app.empty_timeline_text = "No package loaded."
        app._loading = False
        app.playback_playing = False
        app._playback_after_id = None
        app._load_token = 0
        app._load_queue = __import__("queue").Queue()
        app._load_poll_scheduled = False
        app.loading_path = None

        with patch.object(analyzer, "load_session_package") as loader:
            with patch("threading.Thread") as thread_class:
                app.load_path(Path("session_sample.zip"))

        self.assertFalse(loader.called)
        self.assertIn("Loading", app.status_var.value)
        self.assertEqual(app.open_root_button.config["state"], "disabled")
        self.assertEqual(app.open_folder_button.config["state"], "disabled")
        self.assertEqual(app.open_zip_button.config["state"], "disabled")
        thread_class.assert_called_once()
        self.assertTrue(thread_class.call_args.kwargs["daemon"])
        thread_class.return_value.start.assert_called_once()
        self.assertTrue(app.root.after_calls)

    def test_scan_session_directory_builds_sorted_summary_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "session_b.zip"
            second = root / "session_a.zip"
            create_sample_package(first)
            create_sample_package(second)

            with patch.object(analyzer, "load_session_package") as loader:
                entries = analyzer.scan_session_directory(root)

            self.assertEqual([entry.path.name for entry in entries], ["session_a.zip", "session_b.zip"])
            self.assertEqual(entries[0].session_id, "sample")
            self.assertEqual(entries[0].point_id, 123)
            self.assertEqual(entries[0].frame_count, 1)
            self.assertEqual(entries[0].event_count, 4)
            self.assertEqual(entries[0].status, "completed")
            self.assertFalse(loader.called)

    def test_load_path_uses_directory_scan_for_session_collection_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_sample_package(root / "session_sample.zip")
            app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)

            with patch.object(app, "_start_directory_scan") as start_scan:
                with patch.object(app, "_start_package_load") as start_load:
                    app.load_path(root)

            start_scan.assert_called_once_with(root)
            self.assertFalse(start_load.called)

    def test_finish_directory_scan_initializes_stitched_playback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            create_stitched_package(
                root / "session_one.zip",
                session_id="one",
                point_id=1,
                start_epoch_ms=1000,
                frame_times_ms=[0, 20],
            )
            entries = analyzer.scan_session_directory(root)
            timeline = analyzer.build_stitched_timeline(root)
            app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
            app.root = FakeRoot()
            app.package = None
            app.playback_timeline = None
            app.current_playback_frame_index = None
            app.status_var = FakeVar()
            app.timeline = FakeTimeline()
            app.open_root_button = FakeButton()
            app.open_folder_button = FakeButton()
            app.open_zip_button = FakeButton()

            with patch.object(app, "stop_playback") as stop_playback:
                with patch.object(app, "initialize_playback") as initialize_playback:
                    with patch.object(app, "draw_timeline") as draw_timeline:
                        app._finish_directory_scan(
                            analyzer.DirectoryScanResult(
                                token=1,
                                path=root,
                                entries=entries,
                                timeline=timeline,
                            )
                        )

            self.assertEqual(app.playback_timeline, timeline)
            self.assertEqual(len(app.package_entries), 1)
            stop_playback.assert_called_once()
            initialize_playback.assert_called_once()
            draw_timeline.assert_called_once()

    def test_show_stitched_frame_switches_loaded_package_on_demand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "session_first.zip"
            second = root / "session_second.zip"
            create_stitched_package(
                first,
                session_id="first",
                point_id=1,
                start_epoch_ms=1000,
                frame_times_ms=[0],
            )
            create_stitched_package(
                second,
                session_id="second",
                point_id=2,
                start_epoch_ms=2000,
                frame_times_ms=[0],
            )
            timeline = analyzer.build_stitched_timeline(root)
            app = analyzer.SessionTimelineAnalyzerApp.__new__(analyzer.SessionTimelineAnalyzerApp)
            app.package = None
            app._current_frame_package_path = None
            app.selected_event = None

            try:
                with patch.object(app, "show_image"):
                    app.show_stitched_frame(timeline.frames[0])
                    self.assertEqual(app.package.package_path, first)
                    app.show_stitched_frame(timeline.frames[1])
                    self.assertEqual(app.package.package_path, second)
            finally:
                if app.package is not None:
                    app.package.close()

    def test_packaging_scripts_define_standalone_onefile_exe(self):
        repo_root = Path(__file__).resolve().parents[1]
        script = repo_root / "tools" / "package_session_timeline_analyzer.ps1"
        runner = repo_root / "package_session_timeline_analyzer.bat"

        self.assertTrue(script.is_file(), f"missing packaging script: {script}")
        self.assertTrue(runner.is_file(), f"missing packaging runner: {runner}")

        script_text = script.read_text(encoding="utf-8")
        runner_text = runner.read_text(encoding="utf-8")
        self.assertIn('"-m", "PyInstaller"', script_text)
        self.assertIn('"--onefile"', script_text)
        self.assertIn('"--windowed"', script_text)
        self.assertIn('$appName = "session_timeline_analyzer"', script_text)
        self.assertIn("session_timeline_analyzer.py", script_text)
        self.assertIn("session_timeline_analyzer.exe", script_text)
        self.assertIn('"tcl86t.dll"', script_text)
        self.assertIn('"tk86t.dll"', script_text)
        self.assertIn("tools\\package_session_timeline_analyzer.ps1", runner_text)


if __name__ == "__main__":
    unittest.main()
