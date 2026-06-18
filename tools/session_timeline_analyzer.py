from __future__ import annotations

import argparse
import io
import json
import math
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk

from PIL import Image, ImageTk


APP_TITLE = "Session Timeline Analyzer"
TIMELINE_HEIGHT = 190
MARKER_RADIUS = 6
MIN_SPAN_NS = 1_000
PREVIEW_MAX_SIZE = (720, 520)
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


def load_session_package(path: str | Path) -> SessionPackage:
    package_path = Path(path)
    if not package_path.exists():
        raise SessionPackageError(f"session package path not found: {package_path}")
    if package_path.is_file():
        if package_path.suffix.lower() != ".zip":
            raise SessionPackageError(f"session package must be a .zip file: {package_path}")
        source: PackageSource = ZipPackageSource(package_path)
    elif package_path.is_dir():
        source = DirectoryPackageSource(package_path)
    else:
        raise SessionPackageError(f"unsupported session package path: {package_path}")

    try:
        for required in ("manifest.json", "events.jsonl"):
            if not source.exists(required):
                raise SessionPackageError(f"required package file missing: {required}")
        manifest = json.loads(source.read_text("manifest.json"))
        events = parse_events(source.read_text("events.jsonl"))
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
    def __init__(self, root: tk.Tk, initial_path: str | None = None):
        self.root = root
        self.root.title(APP_TITLE)
        self.package: SessionPackage | None = None
        self.viewport: TimelineViewport | None = None
        self.selected_event: TimelineEvent | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.drag_start_x: float | None = None
        self.drag_last_x: float | None = None
        self.drag_moved = False

        self.status_var = tk.StringVar(value="No package loaded.")
        self.package_var = tk.StringVar(value="-")
        self.meta_var = tk.StringVar(value="-")
        self.image_var = tk.StringVar(value="-")
        self._build_ui()
        if initial_path:
            self.load_path(Path(initial_path))

    def _build_ui(self) -> None:
        self.root.geometry("1180x760")
        self.root.minsize(960, 620)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self.root, padding=10)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(1, weight=1)
        ttk.Button(toolbar, text="Open Package", command=self.choose_package).grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, textvariable=self.package_var, anchor="w").grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ttk.Label(toolbar, textvariable=self.meta_var, anchor="e").grid(row=0, column=2, sticky="e", padx=(10, 0))

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))

        left = ttk.Frame(main)
        right = ttk.Frame(main)
        main.add(left, weight=3)
        main.add(right, weight=2)
        left.rowconfigure(0, weight=0)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(2, weight=0)
        right.columnconfigure(0, weight=1)

        self.timeline = tk.Canvas(left, height=TIMELINE_HEIGHT, bg="#ffffff", highlightthickness=1, highlightbackground="#d4d4d4")
        self.timeline.grid(row=0, column=0, sticky="ew")
        self.timeline.bind("<ButtonPress-1>", self.on_timeline_press)
        self.timeline.bind("<B1-Motion>", self.on_timeline_drag)
        self.timeline.bind("<ButtonRelease-1>", self.on_timeline_release)
        self.timeline.bind("<MouseWheel>", self.on_timeline_wheel)
        self.timeline.bind("<Configure>", self.on_timeline_configure)

        columns = ("time", "type", "frame", "duration")
        self.event_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for column, width in (("time", 210), ("type", 180), ("frame", 90), ("duration", 90)):
            self.event_tree.heading(column, text=column)
            self.event_tree.column(column, width=width, stretch=column == "time")
        self.event_tree.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        self.event_tree.bind("<<TreeviewSelect>>", self.on_tree_select)

        self.preview_label = ttk.Label(right, anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        ttk.Label(right, textvariable=self.image_var, anchor="center", wraplength=520).grid(row=1, column=0, sticky="ew", pady=(8, 6))
        self.details = tk.Text(right, height=12, wrap="word")
        self.details.grid(row=2, column=0, sticky="ew")
        self.details.configure(state="disabled")

        ttk.Label(self.root, textvariable=self.status_var, padding=(10, 0, 10, 10)).grid(row=2, column=0, sticky="ew")
        self.root.bind("<Left>", lambda _event: self.select_relative(-1))
        self.root.bind("<Right>", lambda _event: self.select_relative(1))
        self.root.bind("<plus>", lambda _event: self.zoom_keyboard(1.5))
        self.root.bind("<minus>", lambda _event: self.zoom_keyboard(0.75))

    def choose_package(self) -> None:
        selected = filedialog.askopenfilename(
            title="Open session package",
            filetypes=(("Session packages", "session_*.zip"), ("Zip files", "*.zip"), ("All files", "*.*")),
        )
        if selected:
            self.load_path(Path(selected))

    def load_path(self, path: Path) -> None:
        try:
            if self.package is not None:
                self.package.close()
            self.package = load_session_package(path)
            width = max(1, int(self.timeline.winfo_width() or 1000))
            self.viewport = TimelineViewport(self.package.start_ns, self.package.end_ns, width)
            self.selected_event = None
            self.package_var.set(str(path))
            self.meta_var.set(self._metadata_text())
            self.status_var.set("Package loaded.")
            self.populate_tree()
            self.draw_timeline()
            if self.package.events:
                self.select_event(self.package.events[0])
        except Exception as exc:
            self.status_var.set("Package load failed.")
            messagebox.showerror("Package load failed", str(exc))

    def _metadata_text(self) -> str:
        assert self.package is not None
        manifest = self.package.manifest
        session_id = manifest.get("session_id", "-")
        point_id = manifest.get("point_id", "-")
        frames = manifest.get("frame_count", "-")
        online = manifest.get("online_event_count", "-")
        return f"session={session_id}  point={point_id}  frames={frames}  online={online}"

    def populate_tree(self) -> None:
        self.event_tree.delete(*self.event_tree.get_children())
        if self.package is None:
            return
        for event in self.package.events:
            duration = event.raw.get("server_duration_ms")
            self.event_tree.insert(
                "",
                "end",
                iid=str(event.index),
                values=(
                    event.wall_time_iso or event.epoch_ms,
                    event.event_type,
                    event.frame_seq if event.frame_seq is not None else "",
                    duration if duration is not None else "",
                ),
            )

    def draw_timeline(self) -> None:
        self.timeline.delete("all")
        if self.package is None or self.viewport is None:
            self.timeline.create_text(20, TIMELINE_HEIGHT // 2, text="No package loaded.", anchor="w", fill="#525252")
            return
        width = max(1, int(self.timeline.winfo_width() or self.viewport.width))
        self.viewport.width = width
        axis_y = TIMELINE_HEIGHT // 2
        self.timeline.create_line(20, axis_y, width - 20, axis_y, fill="#a3a3a3", width=2)
        self.draw_session_bands(axis_y, width)
        for event in self.package.events:
            x = self.viewport.time_to_x(event.perf_counter_ns)
            if x < -MARKER_RADIUS or x > width + MARKER_RADIUS:
                continue
            color = EVENT_COLORS.get(event.event_type, "#404040")
            y = axis_y - 30 if event.event_type == "offline_frame" else axis_y + 28
            if event.event_type in {"offline_start", "offline_end", "offline_stop_requested"}:
                y = axis_y
            marker = self.timeline.create_oval(
                x - MARKER_RADIUS,
                y - MARKER_RADIUS,
                x + MARKER_RADIUS,
                y + MARKER_RADIUS,
                fill=color,
                outline="#171717" if event == self.selected_event else color,
                width=2 if event == self.selected_event else 1,
            )
            self.timeline.addtag_withtag(f"event_{event.index}", marker)
            if event == self.selected_event:
                self.timeline.create_line(x, 18, x, TIMELINE_HEIGHT - 18, fill="#171717", dash=(4, 3))
                self.timeline.create_text(x + 8, 20, text=event.label, anchor="nw", fill="#171717")
        self.draw_legend(width)

    def draw_session_bands(self, axis_y: int, width: int) -> None:
        assert self.package is not None
        assert self.viewport is not None
        by_type = {event.event_type: event for event in self.package.events}
        start = by_type.get("offline_start")
        stop = by_type.get("offline_stop_requested")
        end = by_type.get("offline_end")
        if start and end:
            x1 = self.viewport.time_to_x(start.perf_counter_ns)
            x2 = self.viewport.time_to_x(end.perf_counter_ns)
            self.timeline.create_rectangle(max(0, x1), axis_y - 62, min(width, x2), axis_y - 48, fill="#dcfce7", outline="")
        if start and stop:
            x1 = self.viewport.time_to_x(start.perf_counter_ns)
            x2 = self.viewport.time_to_x(stop.perf_counter_ns)
            self.timeline.create_rectangle(max(0, x1), axis_y - 44, min(width, x2), axis_y - 32, fill="#dbeafe", outline="")

    def draw_legend(self, width: int) -> None:
        items = [("offline_frame", "frame"), ("online_request", "online"), ("offline_start", "start"), ("offline_end", "end")]
        x = max(10, width - 360)
        y = TIMELINE_HEIGHT - 22
        for event_type, label in items:
            color = EVENT_COLORS.get(event_type, "#404040")
            self.timeline.create_oval(x, y - 5, x + 10, y + 5, fill=color, outline=color)
            self.timeline.create_text(x + 14, y, text=label, anchor="w", fill="#404040")
            x += 82

    def on_timeline_press(self, event) -> None:
        self.drag_start_x = event.x
        self.drag_last_x = event.x
        self.drag_moved = False

    def on_timeline_drag(self, event) -> None:
        if self.viewport is None or self.drag_last_x is None:
            return
        delta = self.drag_last_x - event.x
        if abs(delta) > 0:
            self.drag_moved = True
            self.viewport.pan_pixels(delta)
            self.drag_last_x = event.x
            self.draw_timeline()

    def on_timeline_release(self, event) -> None:
        if self.package is None or self.viewport is None:
            return
        if self.drag_start_x is not None and abs(event.x - self.drag_start_x) > 4:
            return
        times = [timeline_event.perf_counter_ns for timeline_event in self.package.events]
        index = self.viewport.hit_test(times, event.x)
        if index is not None:
            self.select_event(self.package.events[index])

    def on_timeline_wheel(self, event) -> None:
        if self.viewport is None:
            return
        width = max(1, int(self.timeline.winfo_width() or self.viewport.width))
        factor = 1.25 if event.delta > 0 else 0.8
        self.viewport.zoom_at(event.x / width, factor)
        self.draw_timeline()

    def on_timeline_configure(self, _event) -> None:
        if self.viewport is not None:
            self.viewport.width = max(1, int(self.timeline.winfo_width()))
        self.draw_timeline()

    def on_tree_select(self, _event) -> None:
        if self.package is None:
            return
        selected = self.event_tree.selection()
        if not selected:
            return
        index = int(selected[0])
        for event in self.package.events:
            if event.index == index:
                self.select_event(event)
                return

    def select_event(self, event: TimelineEvent) -> None:
        if self.package is None:
            return
        self.selected_event = event
        try:
            image_event = self.package.resolve_image_event(event)
            image = self.package.open_image(image_event)
            self.show_image(image, image_event, event)
        except SessionPackageError as exc:
            self.preview_label.configure(image="")
            self.photo = None
            self.image_var.set(str(exc))
        self.show_details(event)
        if self.event_tree.exists(str(event.index)):
            self.event_tree.selection_set(str(event.index))
            self.event_tree.see(str(event.index))
        self.draw_timeline()

    def show_image(self, image: Image.Image, image_event: TimelineEvent, selected_event: TimelineEvent) -> None:
        preview = image.copy()
        preview.thumbnail(PREVIEW_MAX_SIZE)
        self.photo = ImageTk.PhotoImage(preview)
        self.preview_label.configure(image=self.photo)
        suffix = "" if image_event == selected_event else f" via {image_event.event_type}"
        self.image_var.set(f"{image_event.image_path}{suffix}")

    def show_details(self, event: TimelineEvent) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", json.dumps(event.raw, ensure_ascii=False, indent=2, sort_keys=True))
        self.details.configure(state="disabled")
        self.status_var.set(f"Selected {event.label}")

    def select_relative(self, offset: int) -> None:
        if self.package is None or not self.package.events:
            return
        if self.selected_event is None:
            self.select_event(self.package.events[0])
            return
        current_index = self.package.events.index(self.selected_event)
        next_index = min(len(self.package.events) - 1, max(0, current_index + offset))
        self.select_event(self.package.events[next_index])

    def zoom_keyboard(self, factor: float) -> None:
        if self.viewport is None:
            return
        self.viewport.zoom_at(0.5, factor)
        self.draw_timeline()


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
