from __future__ import annotations

import argparse
import io
import json
import math
import queue
import sys
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from PIL import Image, ImageTk


APP_TITLE = "Session Timeline Analyzer"
DEFAULT_SESSION_ROOT = Path("E:/TestData")
PLAYBACK_TIMELINE_HEIGHT = 96
MIN_SPAN_NS = 1_000
PREVIEW_MAX_SIZE = (1180, 760)
PLAYBACK_SPEEDS = (0.5, 1.0, 2.0, 4.0)
EVENT_COLORS = {
    "offline_start": "#14883e",
    "offline_frame": "#2563eb",
    "online_request": "#c2410c",
    "offline_stop_requested": "#7c3aed",
    "offline_result": "#0f766e",
    "offline_end": "#b91c1c",
    "package_finalized": "#525252",
}


class SessionPackageError(RuntimeError):
    pass


@dataclass(frozen=True)
class TimelineEvent:
    index: int
    event_type: str
    epoch_ms: int
    perf_counter_ns: int
    wall_time_iso: str
    raw: dict

    @property
    def image_path(self) -> str | None:
        path = self.raw.get("path")
        if isinstance(path, str) and path.lower().endswith(".png"):
            return path
        return None

    @property
    def frame_seq(self) -> int | None:
        value = self.raw.get("frame_seq")
        if value is None:
            return None
        return int(value)

    @property
    def label(self) -> str:
        if self.frame_seq is not None:
            return f"{self.event_type} #{self.frame_seq}"
        trace_id = self.raw.get("trace_id")
        if trace_id:
            return f"{self.event_type} {trace_id}"
        return self.event_type

    @property
    def user_marker_label(self) -> str:
        if self.event_type == "offline_start":
            return "offline start"
        if self.event_type == "offline_end":
            return "offline end"
        return self.event_type


class PackageSource:
    def read_text(self, relative_path: str) -> str:
        raise NotImplementedError

    def read_bytes(self, relative_path: str) -> bytes:
        raise NotImplementedError

    def exists(self, relative_path: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ZipPackageSource(PackageSource):
    def __init__(self, path: Path):
        self.path = path
        self._archive = zipfile.ZipFile(path)
        self._names = set(self._archive.namelist())

    def read_text(self, relative_path: str) -> str:
        return self.read_bytes(relative_path).decode("utf-8")

    def read_bytes(self, relative_path: str) -> bytes:
        if relative_path not in self._names:
            raise SessionPackageError(f"required package member missing: {relative_path}")
        return self._archive.read(relative_path)

    def exists(self, relative_path: str) -> bool:
        return relative_path in self._names

    def close(self) -> None:
        self._archive.close()


class DirectoryPackageSource(PackageSource):
    def __init__(self, path: Path):
        self.path = path

    def read_text(self, relative_path: str) -> str:
        return self._path(relative_path).read_text(encoding="utf-8")

    def read_bytes(self, relative_path: str) -> bytes:
        file_path = self._path(relative_path)
        if not file_path.is_file():
            raise SessionPackageError(f"required package file missing: {relative_path}")
        return file_path.read_bytes()

    def exists(self, relative_path: str) -> bool:
        return self._path(relative_path).is_file()

    def _path(self, relative_path: str) -> Path:
        cleaned = relative_path.replace("\\", "/")
        if cleaned.startswith("/") or ".." in Path(cleaned).parts:
            raise SessionPackageError(f"invalid package path: {relative_path}")
        return self.path / cleaned


@dataclass
class SessionPackage:
    source: PackageSource
    package_path: Path
    manifest: dict
    events: list[TimelineEvent]

    @property
    def start_ns(self) -> int:
        return min(event.perf_counter_ns for event in self.events)

    @property
    def end_ns(self) -> int:
        return max(event.perf_counter_ns for event in self.events)

    @property
    def playback_frames(self) -> list[TimelineEvent]:
        return [event for event in self.events if event.event_type == "offline_frame" and event.image_path is not None]

    @property
    def playback_markers(self) -> list[TimelineEvent]:
        return [event for event in self.events if event.event_type in {"offline_start", "offline_end"}]

    def playback_frame_index_for_time(self, time_ns: int) -> int:
        frames = self.playback_frames
        if not frames:
            raise SessionPackageError("session package contains no playable frames")
        target = int(time_ns)
        if target <= frames[0].perf_counter_ns:
            return 0
        for index, event in enumerate(frames[1:], start=1):
            if target < event.perf_counter_ns:
                return index - 1
        return len(frames) - 1

    def open_image(self, event: TimelineEvent) -> Image.Image:
        image_path = event.image_path
        if image_path is None:
            raise SessionPackageError(f"event has no PNG image path: {event.event_type}")
        if not self.source.exists(image_path):
            raise SessionPackageError(f"image path referenced by event is missing: {image_path}")
        with Image.open(io.BytesIO(self.source.read_bytes(image_path))) as image:
            return image.convert("RGB")

    def resolve_image_event(self, event: TimelineEvent) -> TimelineEvent:
        if event.image_path is not None:
            return event
        previous = [
            candidate
            for candidate in self.events
            if candidate.image_path is not None and candidate.perf_counter_ns <= event.perf_counter_ns
        ]
        if previous:
            return previous[-1]
        raise SessionPackageError(f"no PNG frame is available for selected event: {event.event_type}")

    def close(self) -> None:
        self.source.close()


@dataclass(frozen=True)
class StitchedFrame:
    package_path: Path
    package_kind: str
    session_id: str
    point_id: int | None
    frame_index_within_package: int
    event_type: str
    epoch_ms: int
    perf_counter_ns: int
    wall_time_iso: str
    raw: dict

    @property
    def image_path(self) -> str | None:
        path = self.raw.get("path")
        if isinstance(path, str) and path.lower().endswith(".png"):
            return path
        return None


@dataclass(frozen=True)
class StitchedMarker:
    package_path: Path
    session_id: str
    event_type: str
    epoch_ms: int
    perf_counter_ns: int

    @property
    def user_marker_label(self) -> str:
        if self.event_type == "offline_start":
            return "offline start"
        if self.event_type == "offline_end":
            return "offline end"
        return self.event_type


@dataclass
class StitchedPlaybackTimeline:
    root_path: Path
    frames: list[StitchedFrame]
    markers: list[StitchedMarker]

    @property
    def start_ns(self) -> int:
        if self.frames:
            return self.frames[0].perf_counter_ns
        if self.markers:
            return min(marker.perf_counter_ns for marker in self.markers)
        raise SessionPackageError("stitched playback contains no timeline events")

    @property
    def end_ns(self) -> int:
        if self.frames:
            return self.frames[-1].perf_counter_ns
        if self.markers:
            return max(marker.perf_counter_ns for marker in self.markers)
        raise SessionPackageError("stitched playback contains no timeline events")

    def frame_index_for_time(self, time_ns: int) -> int:
        if not self.frames:
            raise SessionPackageError("stitched playback contains no playable frames")
        target = int(time_ns)
        if target <= self.frames[0].perf_counter_ns:
            return 0
        for index, frame in enumerate(self.frames[1:], start=1):
            if target < frame.perf_counter_ns:
                return index - 1
        return len(self.frames) - 1

    def frame_delay_ms(self, frame_index: int) -> int:
        if not self.frames:
            raise SessionPackageError("stitched playback contains no playable frames")
        index = min(len(self.frames) - 1, max(0, int(frame_index)))
        if index >= len(self.frames) - 1:
            return 0
        current = self.frames[index]
        next_frame = self.frames[index + 1]
        return max(1, int(next_frame.epoch_ms - current.epoch_ms))


@dataclass(frozen=True)
class PackageSummary:
    path: Path
    package_kind: str
    session_id: str | None
    point_id: int | None
    frame_count: int | None
    online_event_count: int | None
    event_count: int
    package_status: str | None
    size_bytes: int
    modified_epoch_ms: int

    @property
    def status(self) -> str | None:
        return self.package_status


@dataclass(frozen=True)
class PackageLoadResult:
    token: int
    path: Path
    package: SessionPackage | None = None
    error: Exception | None = None


@dataclass(frozen=True)
class DirectoryScanResult:
    token: int
    path: Path
    entries: list[PackageSummary] | None = None
    timeline: StitchedPlaybackTimeline | None = None
    error: Exception | None = None


@dataclass
class TimelineViewport:
    start_ns: int
    end_ns: int
    width: int
    view_start_ns: int | None = None
    view_end_ns: int | None = None

    def __post_init__(self) -> None:
        if self.view_start_ns is None:
            self.view_start_ns = int(self.start_ns)
        if self.view_end_ns is None:
            self.view_end_ns = int(self.end_ns)
        if self.view_end_ns <= self.view_start_ns:
            self.view_end_ns = self.view_start_ns + MIN_SPAN_NS

    @property
    def span_ns(self) -> int:
        return max(MIN_SPAN_NS, int(self.view_end_ns) - int(self.view_start_ns))

    def time_to_x(self, time_ns: int) -> float:
        width = max(1, int(self.width))
        return ((int(time_ns) - int(self.view_start_ns)) / self.span_ns) * width

    def x_to_time(self, x: float) -> int:
        width = max(1, int(self.width))
        return int(self.view_start_ns + (float(x) / width) * self.span_ns)

    def pan_pixels(self, delta_px: float) -> None:
        width = max(1, int(self.width))
        delta_ns = int((float(delta_px) / width) * self.span_ns)
        self.view_start_ns += delta_ns
        self.view_end_ns += delta_ns
        self._clamp()

    def zoom_at(self, x_fraction: float, factor: float) -> None:
        factor = max(0.1, float(factor))
        x_fraction = min(1.0, max(0.0, float(x_fraction)))
        focus = int(self.view_start_ns + self.span_ns * x_fraction)
        new_span = max(MIN_SPAN_NS, int(self.span_ns / factor))
        left = int(focus - new_span * x_fraction)
        right = left + new_span
        self.view_start_ns = left
        self.view_end_ns = right
        self._clamp()

    def hit_test(self, event_times_ns: list[int], x: float, tolerance_px: int = 8) -> int | None:
        best_index = None
        best_distance = math.inf
        for index, time_ns in enumerate(event_times_ns):
            distance = abs(self.time_to_x(time_ns) - float(x))
            if distance <= tolerance_px and distance < best_distance:
                best_index = index
                best_distance = distance
        return best_index

    def _clamp(self) -> None:
        total_start = int(self.start_ns)
        total_end = max(int(self.end_ns), total_start + MIN_SPAN_NS)
        span = self.span_ns
        if span >= total_end - total_start:
            self.view_start_ns = total_start
            self.view_end_ns = total_end
            return
        if self.view_start_ns < total_start:
            self.view_start_ns = total_start
            self.view_end_ns = total_start + span
        if self.view_end_ns > total_end:
            self.view_end_ns = total_end
            self.view_start_ns = total_end - span


def is_extracted_package_directory(path: Path) -> bool:
    return path.is_dir() and (path / "manifest.json").is_file() and (path / "events.jsonl").is_file()


def create_package_source(path: str | Path) -> tuple[Path, PackageSource]:
    package_path = Path(path)
    if not package_path.exists():
        raise SessionPackageError(f"session package path not found: {package_path}")
    if package_path.is_file():
        if package_path.suffix.lower() != ".zip":
            raise SessionPackageError(f"session package must be a .zip file: {package_path}")
        return package_path, ZipPackageSource(package_path)
    if is_extracted_package_directory(package_path):
        return package_path, DirectoryPackageSource(package_path)
    if package_path.is_dir():
        raise SessionPackageError(f"session package directory is missing manifest.json or events.jsonl: {package_path}")
    raise SessionPackageError(f"unsupported session package path: {package_path}")


def _parse_optional_int(value, field_name: str, package_path: Path) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception as exc:
        raise SessionPackageError(f"{package_path} manifest field {field_name} must be numeric") from exc


def _read_manifest_and_events_text(source: PackageSource) -> tuple[dict, str]:
    for required in ("manifest.json", "events.jsonl"):
        if not source.exists(required):
            raise SessionPackageError(f"required package file missing: {required}")
    manifest = json.loads(source.read_text("manifest.json"))
    events_text = source.read_text("events.jsonl")
    return manifest, events_text


def build_package_summary(path: str | Path) -> PackageSummary:
    package_path, source = create_package_source(path)
    try:
        manifest, events_text = _read_manifest_and_events_text(source)
        session_id = manifest.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise SessionPackageError(f"{package_path} manifest field session_id must be a string")
        package_status = manifest.get("package_status")
        if package_status is not None and not isinstance(package_status, str):
            raise SessionPackageError(f"{package_path} manifest field package_status must be a string")
        event_count = sum(1 for line in events_text.splitlines() if line.strip())
        stat = package_path.stat()
        return PackageSummary(
            path=package_path,
            package_kind="directory" if package_path.is_dir() else "zip",
            session_id=session_id,
            point_id=_parse_optional_int(manifest.get("point_id"), "point_id", package_path),
            frame_count=_parse_optional_int(manifest.get("frame_count"), "frame_count", package_path),
            online_event_count=_parse_optional_int(manifest.get("online_event_count"), "online_event_count", package_path),
            event_count=event_count,
            package_status=package_status,
            size_bytes=_package_size_bytes(package_path, stat.st_size),
            modified_epoch_ms=int(stat.st_mtime * 1000),
        )
    finally:
        source.close()


def _package_size_bytes(path: Path, file_size: int) -> int:
    if path.is_file():
        return int(file_size)
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def scan_session_directory(path: str | Path) -> list[PackageSummary]:
    root = Path(path)
    if not root.exists():
        raise SessionPackageError(f"session directory path not found: {root}")
    if not root.is_dir():
        raise SessionPackageError(f"session directory path must be a directory: {root}")
    entries: list[PackageSummary] = []
    for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
        if child.is_file() and child.name.lower().startswith("session_") and child.suffix.lower() == ".zip":
            entries.append(build_package_summary(child))
            continue
        if is_extracted_package_directory(child):
            entries.append(build_package_summary(child))
    return entries


def build_stitched_timeline(path: str | Path) -> StitchedPlaybackTimeline:
    root = Path(path)
    entries = scan_session_directory(root)
    return build_stitched_timeline_from_entries(root, entries)


def build_stitched_timeline_from_entries(root: Path, entries: list[PackageSummary]) -> StitchedPlaybackTimeline:
    frames: list[StitchedFrame] = []
    markers: list[StitchedMarker] = []
    for entry in entries:
        package = load_session_package(entry.path)
        try:
            session_id = str(package.manifest.get("session_id") or entry.path.stem)
            point_id = package.manifest.get("point_id")
            for frame_index, event in enumerate(package.playback_frames):
                frames.append(
                    StitchedFrame(
                        package_path=entry.path,
                        package_kind=entry.package_kind,
                        session_id=session_id,
                        point_id=int(point_id) if point_id is not None else None,
                        frame_index_within_package=frame_index,
                        event_type=event.event_type,
                        epoch_ms=event.epoch_ms,
                        perf_counter_ns=event.perf_counter_ns,
                        wall_time_iso=event.wall_time_iso,
                        raw=dict(event.raw),
                    )
                )
            for marker in package.playback_markers:
                markers.append(
                    StitchedMarker(
                        package_path=entry.path,
                        session_id=session_id,
                        event_type=marker.event_type,
                        epoch_ms=marker.epoch_ms,
                        perf_counter_ns=marker.perf_counter_ns,
                    )
                )
        finally:
            package.close()
    frames.sort(key=lambda item: (item.epoch_ms, item.perf_counter_ns, str(item.package_path), item.frame_index_within_package))
    markers.sort(key=lambda item: (item.epoch_ms, item.perf_counter_ns, str(item.package_path), item.event_type))
    if not frames:
        raise SessionPackageError(f"session root contains no playable frames: {root}")
    return StitchedPlaybackTimeline(root_path=root, frames=frames, markers=markers)


def load_session_package(path: str | Path) -> SessionPackage:
    package_path, source = create_package_source(path)
    try:
        manifest, events_text = _read_manifest_and_events_text(source)
        events = parse_events(events_text)
        if not events:
            raise SessionPackageError("events.jsonl contains no events")
        return SessionPackage(source=source, package_path=package_path, manifest=manifest, events=events)
    except Exception:
        source.close()
        raise


def parse_events(text: str) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise SessionPackageError(f"events.jsonl line {line_number} is invalid JSON") from exc
        event_type = payload.get("event_type")
        if not isinstance(event_type, str) or not event_type:
            raise SessionPackageError(f"events.jsonl line {line_number} missing event_type")
        try:
            epoch_ms = int(payload.get("epoch_ms"))
            perf_counter_ns = int(payload.get("perf_counter_ns"))
        except Exception as exc:
            raise SessionPackageError(f"events.jsonl line {line_number} missing numeric timestamps") from exc
        events.append(
            TimelineEvent(
                index=len(events),
                event_type=event_type,
                epoch_ms=epoch_ms,
                perf_counter_ns=perf_counter_ns,
                wall_time_iso=str(payload.get("wall_time_iso") or ""),
                raw=payload,
            )
        )
    return sorted(events, key=lambda event: (event.perf_counter_ns, event.index))


class SessionTimelineAnalyzerApp:
    def __init__(self, root: tk.Tk, initial_path: str | None = None, auto_prompt: bool = True):
        self.root = root
        self.root.title(APP_TITLE)
        self.package: SessionPackage | None = None
        self.playback_timeline: StitchedPlaybackTimeline | None = None
        self.package_entries: list[PackageSummary] = []
        self.active_directory: Path | None = None
        self.viewport: TimelineViewport | None = None
        self.selected_event: TimelineEvent | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.drag_start_x: float | None = None
        self.drag_last_x: float | None = None
        self.drag_moved = False
        self.current_playback_frame_index: int | None = None
        self.playback_playing = False
        self.playback_speed = 1.0
        self._playback_after_id = None
        self._playback_scrubbing = False
        self._syncing_event_tree_selection = False
        self._load_token = 0
        self._load_queue: queue.Queue[PackageLoadResult] = queue.Queue()
        self._load_poll_scheduled = False
        self._loading = False
        self.loading_path: Path | None = None
        self._scan_token = 0
        self._scan_queue: queue.Queue[DirectoryScanResult] = queue.Queue()
        self._scan_poll_scheduled = False
        self._scanning = False
        self.empty_timeline_text = "No package loaded."
        self._current_frame_package_path: Path | None = None
        self._startup_path = Path(initial_path) if initial_path else (DEFAULT_SESSION_ROOT if DEFAULT_SESSION_ROOT.is_dir() else None)
        self.menu_bar = None

        self.status_var = tk.StringVar(value="No package loaded.")
        self.image_var = tk.StringVar(value="")
        self.speed_var = tk.StringVar(value="1.0x")
        self._build_menu()
        self._build_ui()
        if self._startup_path is not None:
            self.root.after(0, lambda: self.load_path(self._startup_path))
        elif auto_prompt:
            self.root.after(150, self.choose_session_root)

    def _build_menu(self) -> None:
        self.menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(self.menu_bar, tearoff=0)
        file_menu.add_command(label="选择基础目录", command=self.choose_base_directory)
        file_menu.add_command(label="打开 Zip", command=self.choose_package_zip)
        file_menu.add_command(label="打开解压目录", command=self.choose_package_folder)
        self.menu_bar.add_cascade(label="文件", menu=file_menu)
        self.root.configure(menu=self.menu_bar)

    def _build_ui(self) -> None:
        self.root.geometry("1280x860")
        self.root.minsize(900, 620)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main = ttk.Frame(self.root, padding=0)
        main.grid(row=0, column=0, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.rowconfigure(1, weight=0)
        main.rowconfigure(2, weight=0)
        main.columnconfigure(0, weight=1)

        self.preview_label = ttk.Label(main, anchor="center", background="#000000")
        self.preview_label.grid(row=0, column=0, sticky="nsew")

        self.controls_frame = self._build_controls(main)
        self.controls_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 4))

        self.playback_time_var = tk.StringVar(value="0 / 0")
        self.timeline = tk.Canvas(
            main,
            height=PLAYBACK_TIMELINE_HEIGHT,
            bg="#0f0f0f",
            highlightthickness=0,
            bd=0,
        )
        self.timeline.grid(row=2, column=0, sticky="ew")
        self.timeline.bind("<ButtonPress-1>", self.on_timeline_press)
        self.timeline.bind("<B1-Motion>", self.on_timeline_drag)
        self.timeline.bind("<ButtonRelease-1>", self.on_timeline_release)
        self.timeline.bind("<Configure>", self.on_timeline_configure)
        self.timeline.bind("<MouseWheel>", self.on_timeline_mousewheel)
        self.root.bind("<Left>", lambda _event: self.select_relative(-1))
        self.root.bind("<Right>", lambda _event: self.select_relative(1))
        self.root.bind("<space>", lambda _event: self.toggle_playback())

    def _build_controls(self, parent) -> ttk.Frame:
        if not hasattr(self, "speed_var"):
            self.speed_var = tk.StringVar(value=f"{getattr(self, 'playback_speed', 1.0):.1f}x")
        controls = ttk.Frame(parent, padding=0)
        controls.columnconfigure(5, weight=1)
        self.play_button = ttk.Button(controls, text="Play", command=self.play)
        self.play_button.grid(row=0, column=0, sticky="w")
        self.pause_button = ttk.Button(controls, text="Pause", command=self.pause)
        self.pause_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(controls, text="Speed").grid(row=0, column=2, sticky="w", padx=(16, 6))
        speed_column = 3
        self.speed_buttons = []
        for speed in PLAYBACK_SPEEDS:
            label = f"{speed:.1f}x"
            button = ttk.Button(controls, text=label, command=lambda value=speed: self.set_playback_speed(value))
            button.grid(row=0, column=speed_column, sticky="w", padx=(0, 6))
            self.speed_buttons.append(button)
            speed_column += 1
        self.speed_value_label = ttk.Label(controls, textvariable=self.speed_var, anchor="e")
        self.speed_value_label.grid(row=0, column=speed_column, sticky="e")
        return controls

    def choose_package(self) -> None:
        self.choose_package_zip()

    def choose_base_directory(self) -> None:
        self.choose_session_root()

    def play(self) -> None:
        if self.playback_timeline is None or not self.playback_timeline.frames:
            return
        if self.playback_playing:
            return
        self.playback_playing = True
        self._schedule_playback_tick()

    def pause(self) -> None:
        self.stop_playback()

    def set_playback_speed(self, speed: float) -> None:
        self.playback_speed = float(speed)
        self.speed_var.set(f"{self.playback_speed:.1f}x")
        self.stop_playback()

    def choose_session_root(self) -> None:
        selected = filedialog.askdirectory(title="Open session package root directory")
        if selected:
            self.load_path(Path(selected))

    def choose_package_zip(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open session package",
            filetypes=(("Session packages", "session_*.zip"), ("Zip files", "*.zip"), ("All files", "*.*")),
        )
        if selected:
            self.load_path(Path(selected))

    def choose_package_folder(self) -> None:
        selected = filedialog.askdirectory(title="Open extracted session package folder")
        if selected:
            self.load_path(Path(selected))

    def load_path(self, path: Path) -> None:
        path = Path(path)
        if path.is_dir() and not is_extracted_package_directory(path):
            self._start_directory_scan(path)
            return
        self._start_package_load(path)

    def _start_directory_scan(self, path: Path) -> None:
        self._scan_token += 1
        token = self._scan_token
        self._scanning = True
        self.active_directory = path
        self.playback_timeline = None
        self.current_playback_frame_index = None
        self.status_var.set(f"Indexing session root: {path}")
        self._set_open_controls_enabled(False)
        worker = threading.Thread(target=self._background_scan_directory, args=(token, path), daemon=True)
        worker.start()
        self._schedule_scan_poll()

    def _background_scan_directory(self, token: int, path: Path) -> None:
        try:
            entries = scan_session_directory(path)
            timeline = build_stitched_timeline_from_entries(path, entries)
        except Exception as exc:
            self._scan_queue.put(DirectoryScanResult(token=token, path=path, error=exc))
        else:
            self._scan_queue.put(DirectoryScanResult(token=token, path=path, entries=entries, timeline=timeline))

    def _schedule_scan_poll(self) -> None:
        if self._scan_poll_scheduled:
            return
        self._scan_poll_scheduled = True
        self.root.after(50, self._poll_scan_queue)

    def _poll_scan_queue(self) -> None:
        self._scan_poll_scheduled = False
        try:
            while True:
                result = self._scan_queue.get_nowait()
                if result.token != self._scan_token:
                    continue
                self._finish_directory_scan(result)
                return
        except queue.Empty:
            pass
        if self._scanning:
            self._schedule_scan_poll()

    def _finish_directory_scan(self, result: DirectoryScanResult) -> None:
        self._scanning = False
        self._set_open_controls_enabled(True)
        if result.error is not None:
            self.status_var.set("Session root indexing failed.")
            messagebox.showerror("Directory scan failed", str(result.error))
            return
        self.package_entries = result.entries or []
        self.playback_timeline = result.timeline
        if self.playback_timeline is None:
            raise SessionPackageError("stitched playback timeline missing from directory scan result")
        timeline_width = 1000
        if hasattr(self.timeline, "winfo_width"):
            timeline_width = max(1, int(self.timeline.winfo_width() or 1000))
        self.viewport = TimelineViewport(self.playback_timeline.start_ns, self.playback_timeline.end_ns, timeline_width)
        self.current_playback_frame_index = None
        if self.package is not None:
            self.package.close()
        self.package = None
        self._current_frame_package_path = None
        self.stop_playback()
        self.status_var.set(f"Indexed {len(self.package_entries)} package(s).")
        self.initialize_playback()
        self.draw_timeline()

    def _start_package_load(self, path: Path) -> None:
        self._load_token += 1
        token = self._load_token
        self._loading = True
        self.loading_path = path
        self.status_var.set(f"Loading package: {path}")
        self.image_var.set("-")
        self.empty_timeline_text = "Loading package..."
        self.stop_playback()
        self._set_open_controls_enabled(False)
        if self.package is None:
            self.draw_timeline()
        worker = threading.Thread(target=self._background_load_package, args=(token, path), daemon=True)
        worker.start()
        self._schedule_load_poll()

    def _background_load_package(self, token: int, path: Path) -> None:
        try:
            package = load_session_package(path)
        except Exception as exc:
            self._load_queue.put(PackageLoadResult(token=token, path=path, error=exc))
        else:
            self._load_queue.put(PackageLoadResult(token=token, path=path, package=package))

    def _schedule_load_poll(self) -> None:
        if self._load_poll_scheduled:
            return
        self._load_poll_scheduled = True
        self.root.after(50, self._poll_load_queue)

    def _poll_load_queue(self) -> None:
        self._load_poll_scheduled = False
        try:
            while True:
                result = self._load_queue.get_nowait()
                if result.token != self._load_token:
                    if result.package is not None:
                        result.package.close()
                    continue
                self._finish_package_load(result)
                return
        except queue.Empty:
            pass
        if self._loading:
            self._schedule_load_poll()

    def _finish_package_load(self, result: PackageLoadResult) -> None:
        self._loading = False
        self.loading_path = None
        self._set_open_controls_enabled(True)
        self.empty_timeline_text = "No package loaded."
        if result.error is not None:
            self.status_var.set("Package load failed.")
            if self.package is None and self.playback_timeline is None:
                self.draw_timeline()
            messagebox.showerror("Package load failed", str(result.error))
            return

        assert result.package is not None
        old_package = self.package
        self.package = result.package
        self.playback_timeline = StitchedPlaybackTimeline(
            root_path=result.path.parent if result.path.is_file() else result.path,
            frames=[
                StitchedFrame(
                    package_path=result.path,
                    package_kind="directory" if result.path.is_dir() else "zip",
                    session_id=str(result.package.manifest.get("session_id") or result.path.stem),
                    point_id=int(result.package.manifest.get("point_id")) if result.package.manifest.get("point_id") is not None else None,
                    frame_index_within_package=index,
                    event_type=event.event_type,
                    epoch_ms=event.epoch_ms,
                    perf_counter_ns=event.perf_counter_ns,
                    wall_time_iso=event.wall_time_iso,
                    raw=dict(event.raw),
                )
                for index, event in enumerate(result.package.playback_frames)
            ],
            markers=[
                StitchedMarker(
                    package_path=result.path,
                    session_id=str(result.package.manifest.get("session_id") or result.path.stem),
                    event_type=marker.event_type,
                    epoch_ms=marker.epoch_ms,
                    perf_counter_ns=marker.perf_counter_ns,
                )
                for marker in result.package.playback_markers
            ],
        )
        if old_package is not None:
            old_package.close()
        width = max(1, int(self.timeline.winfo_width() or 1000))
        self.viewport = TimelineViewport(self.playback_timeline.start_ns, self.playback_timeline.end_ns, width)
        self.selected_event = None
        self.current_playback_frame_index = None
        self._current_frame_package_path = result.path
        self.status_var.set("Package loaded.")
        self.draw_timeline()
        self.initialize_playback()

    def _set_open_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for button_name in ("open_root_button", "open_folder_button", "open_zip_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.configure(state=state)

    def initialize_playback(self) -> None:
        if getattr(self, "playback_timeline", None) is None:
            return
        if not self.playback_timeline.frames:
            self.preview_label.configure(image="")
            self.photo = None
            self.image_var.set("No playable frames.")
            self.playback_time_var.set("0 / 0")
            return
        self.display_playback_frame(0)

    def draw_timeline(self) -> None:
        self.timeline.delete("all")
        if getattr(self, "playback_timeline", None) is None or getattr(self, "viewport", None) is None:
            self.timeline.create_text(20, PLAYBACK_TIMELINE_HEIGHT // 2, text=self.empty_timeline_text, anchor="w", fill="#d4d4d4")
            return
        width = max(1, int(self.timeline.winfo_width() or self.viewport.width))
        self.viewport.width = width
        bar_left = 20
        bar_right = max(bar_left + 1, width - 20)
        axis_y = PLAYBACK_TIMELINE_HEIGHT - 24
        self.timeline.create_line(bar_left, axis_y, bar_right, axis_y, fill="#4b5563", width=4)
        marker_top = 12
        for tick_time_ns in self._build_timeline_ticks(6):
            x = self._viewport_time_to_timeline_x(tick_time_ns, bar_left, bar_right)
            self.timeline.create_line(x, axis_y - 10, x, axis_y + 4, fill="#6b7280", width=1)
            self.timeline.create_text(x, axis_y - 16, text=self._format_time_label(tick_time_ns), anchor="s", fill="#cbd5e1")
        for marker in self.playback_timeline.markers:
            x = self._time_to_timeline_x(marker.perf_counter_ns, bar_left, bar_right)
            self.timeline.create_line(x, marker_top + 18, x, axis_y, fill=EVENT_COLORS.get(marker.event_type, "#d4d4d4"), width=2)
            self.timeline.create_text(x, marker_top, text=marker.user_marker_label, anchor="n", fill="#f5f5f5")
        playback_text = self.playback_time_var.get() if hasattr(self.playback_time_var, "get") else ""
        self.timeline.create_text(bar_left, axis_y + 16, text=playback_text, anchor="w", fill="#e5e7eb")
        if self.current_playback_frame_index is not None and self.playback_timeline.frames:
            current = self.playback_timeline.frames[self.current_playback_frame_index]
            x = self._time_to_timeline_x(current.perf_counter_ns, bar_left, bar_right)
            self.timeline.create_line(x, marker_top + 8, x, axis_y + 8, fill="#f8fafc", width=2)
            self.timeline.create_oval(x - 6, axis_y - 6, x + 6, axis_y + 6, fill="#f8fafc", outline="#f8fafc")

    def _time_to_timeline_x(self, time_ns: int, bar_left: int, bar_right: int) -> float:
        assert self.playback_timeline is not None
        start = self.playback_timeline.start_ns
        end = max(self.playback_timeline.end_ns, start + MIN_SPAN_NS)
        span = max(MIN_SPAN_NS, end - start)
        fraction = (int(time_ns) - start) / span
        fraction = min(1.0, max(0.0, fraction))
        return bar_left + (bar_right - bar_left) * fraction

    def _viewport_time_to_timeline_x(self, time_ns: int, bar_left: int, bar_right: int) -> float:
        assert self.viewport is not None
        span = max(MIN_SPAN_NS, self.viewport.span_ns)
        fraction = (int(time_ns) - int(self.viewport.view_start_ns)) / span
        fraction = min(1.0, max(0.0, fraction))
        return bar_left + (bar_right - bar_left) * fraction

    def _build_timeline_ticks(self, count: int = 6) -> list[int]:
        if self.viewport is None:
            return []
        tick_count = max(2, int(count))
        start = int(self.viewport.view_start_ns)
        span = max(MIN_SPAN_NS, self.viewport.span_ns)
        step = max(1, span // (tick_count - 1))
        ticks = [start + step * index for index in range(tick_count - 1)]
        ticks.append(int(self.viewport.view_end_ns))
        return ticks

    def _format_time_label(self, time_ns: int) -> str:
        timestamp_ms = int(time_ns // 1_000_000)
        seconds = timestamp_ms / 1000.0
        minutes = int(seconds // 60)
        seconds_remainder = seconds - (minutes * 60)
        return f"{minutes:02d}:{seconds_remainder:05.2f}"

    def _timeline_x_to_time(self, x: float) -> int:
        assert self.playback_timeline is not None
        width = max(1, int(self.timeline.winfo_width() or 1))
        bar_left = 20
        bar_right = max(bar_left + 1, width - 20)
        if bar_right <= bar_left:
            return self.playback_timeline.start_ns
        fraction = (float(x) - bar_left) / (bar_right - bar_left)
        fraction = min(1.0, max(0.0, fraction))
        return int(self.playback_timeline.start_ns + (self.playback_timeline.end_ns - self.playback_timeline.start_ns) * fraction)

    def on_timeline_press(self, event) -> None:
        if self.playback_timeline is None or not self.playback_timeline.frames:
            return
        self._playback_scrubbing = True
        self.stop_playback()
        self.scrub_to_timeline_x(event.x)

    def on_timeline_drag(self, event) -> None:
        if not self._playback_scrubbing:
            return
        self.scrub_to_timeline_x(event.x)

    def on_timeline_release(self, event) -> None:
        if not self._playback_scrubbing:
            return
        self._playback_scrubbing = False
        self.scrub_to_timeline_x(event.x)

    def on_timeline_configure(self, _event) -> None:
        self.draw_timeline()

    def on_timeline_mousewheel(self, event) -> None:
        if self.playback_timeline is None or self.viewport is None:
            return
        width = max(1, int(self.timeline.winfo_width() or self.viewport.width))
        x_fraction = min(1.0, max(0.0, float(getattr(event, "x", width / 2)) / width))
        delta = getattr(event, "delta", 0)
        factor = 1.25 if delta > 0 else 0.8
        if delta == 0:
            return
        self.viewport.zoom_at(x_fraction, factor)
        self.draw_timeline()

    def show_image(self, image: Image.Image, image_event: TimelineEvent, selected_event: TimelineEvent) -> None:
        preview = image.copy()
        preview.thumbnail(PREVIEW_MAX_SIZE)
        self.photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.photo)
        suffix = "" if image_event == selected_event else f" via {image_event.event_type}"
        self.image_var.set(f"{image_event.image_path}{suffix}")

    def show_stitched_frame(self, frame: StitchedFrame) -> None:
        package = self._ensure_frame_package_loaded(frame.package_path)
        matching_events = [
            event
            for event in package.playback_frames
            if event.epoch_ms == frame.epoch_ms and event.perf_counter_ns == frame.perf_counter_ns and event.image_path == frame.image_path
        ]
        if not matching_events:
            raise SessionPackageError(f"stitched frame missing in package playback stream: {frame.package_path}")
        image_event = matching_events[0]
        image = package.open_image(image_event)
        self.selected_event = image_event
        self.show_image(image, image_event, image_event)

    def _ensure_frame_package_loaded(self, package_path: Path) -> SessionPackage:
        if self.package is not None and self._current_frame_package_path == package_path:
            return self.package
        package = load_session_package(package_path)
        old_package = self.package
        self.package = package
        self._current_frame_package_path = package_path
        if old_package is not None:
            old_package.close()
        return package

    def select_relative(self, offset: int) -> None:
        if self.playback_timeline is None or not self.playback_timeline.frames:
            return
        if self.current_playback_frame_index is None:
            self.display_playback_frame(0)
            return
        next_index = min(len(self.playback_timeline.frames) - 1, max(0, self.current_playback_frame_index + offset))
        self.display_playback_frame(next_index)

    def display_playback_frame(self, frame_index: int) -> None:
        if getattr(self, "playback_timeline", None) is None:
            return
        frames = self.playback_timeline.frames
        if not frames:
            raise SessionPackageError("stitched playback contains no playable frames")
        frame_index = min(len(frames) - 1, max(0, int(frame_index)))
        self.current_playback_frame_index = frame_index
        frame = frames[frame_index]
        self.show_stitched_frame(frame)
        total = len(frames)
        self.playback_time_var.set(f"{frame_index + 1} / {total}")
        status_var = getattr(self, "status_var", None)
        if status_var is not None:
            status_var.set(f"{frame.session_id}  {frame_index + 1}/{total}")
        self.draw_timeline()

    def scrub_to_timeline_x(self, x: float) -> None:
        if self.playback_timeline is None or not self.playback_timeline.frames:
            return
        frame_index = self.playback_timeline.frame_index_for_time(self._timeline_x_to_time(x))
        self.display_playback_frame(frame_index)

    def toggle_playback(self) -> None:
        if self.playback_playing:
            self.stop_playback()
            return
        self.play()

    def stop_playback(self) -> None:
        self.playback_playing = False
        if self._playback_after_id is not None:
            try:
                self.root.after_cancel(self._playback_after_id)
            except Exception:
                pass
            self._playback_after_id = None

    def _schedule_playback_tick(self) -> None:
        if self.playback_timeline is None:
            return
        current_index = 0 if self.current_playback_frame_index is None else self.current_playback_frame_index
        delay_ms = self.playback_timeline.frame_delay_ms(current_index)
        speed = max(0.1, float(getattr(self, "playback_speed", 1.0)))
        delay_ms = max(1, int(delay_ms / speed))
        self._playback_after_id = self.root.after(delay_ms, self._playback_tick)

    def _playback_tick(self) -> None:
        self._playback_after_id = None
        if not self.playback_playing or self.playback_timeline is None or not self.playback_timeline.frames:
            return
        if self.current_playback_frame_index is None:
            self.display_playback_frame(0)
        elif self.current_playback_frame_index >= len(self.playback_timeline.frames) - 1:
            self.stop_playback()
            return
        else:
            self.display_playback_frame(self.current_playback_frame_index + 1)
        if self.playback_playing:
            self._schedule_playback_tick()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open an algorithm session package in a desktop timeline analyzer.")
    parser.add_argument("package", nargs="?", help="Path to session_<id>.zip or an extracted package directory.")
    parser.add_argument("--self-test-load", help="Load a package and print a JSON summary without starting the GUI.")
    args = parser.parse_args(argv)
    if args.self_test_load:
        package = load_session_package(args.self_test_load)
        try:
            print(
                json.dumps(
                    {
                        "session_id": package.manifest.get("session_id"),
                        "event_count": len(package.events),
                        "frame_event_count": len([event for event in package.events if event.image_path is not None]),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        finally:
            package.close()
        return 0
    root = tk.Tk()
    SessionTimelineAnalyzerApp(root, initial_path=args.package)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
