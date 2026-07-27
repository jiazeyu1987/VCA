from __future__ import annotations

import argparse
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Iterable

from PIL import Image, ImageColor, ImageDraw, ImageTk


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
DEFAULT_COLOR = "#FFD600"
PREVIEW_MAX_SIZE = (980, 720)
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
ORIGINAL_IMAGES_DIR = "original_images"
MASKS_DIR = "masks"
EXPORT_IMAGE_SUFFIX = ".png"


@dataclass(frozen=True)
class Annotation:
    kind: str
    coords: tuple[int, ...]
    color: str = DEFAULT_COLOR
    width: int = 3
    label: str = ""


@dataclass
class ImageAnnotationRecord:
    path: Path
    annotations: list[Annotation] = field(default_factory=list)
    session_zip_path: Path | None = None
    member_name: str = ""
    session_id: str = ""
    point_id: str = ""

    @property
    def is_zip_member(self) -> bool:
        return self.session_zip_path is not None and bool(self.member_name)

    @property
    def display_name(self) -> str:
        if self.is_zip_member:
            return f"{self.session_zip_path.name} :: {self.member_name}"
        return self.path.name

    @property
    def original_name(self) -> str:
        if self.is_zip_member:
            return PurePosixPath(self.member_name).name
        return self.path.name

    @property
    def original_path_text(self) -> str:
        if self.is_zip_member:
            return f"{self.session_zip_path.resolve()}!/{self.member_name}"
        return str(self.path.resolve())

    @property
    def source_type(self) -> str:
        return "session_zip" if self.is_zip_member else "file"

    def open_image(self) -> Image.Image:
        if self.is_zip_member:
            with zipfile.ZipFile(self.session_zip_path) as zf:
                with zf.open(self.member_name) as member:
                    with Image.open(member) as image:
                        image.load()
                        return image.copy()
        if not self.path.is_file():
            raise FileNotFoundError(f"source image not found: {self.path}")
        with Image.open(self.path) as image:
            image.load()
            return image.copy()


@dataclass(frozen=True)
class ExportMappingRow:
    original_name: str
    export_name: str
    original_path: Path | str
    original_export_path: Path
    mask_path: Path
    annotation_count: int
    source_type: str = "file"
    session_zip: str = ""
    session_id: str = ""
    point_id: str = ""
    original_member: str = ""


@dataclass(frozen=True)
class PreviewLayout:
    x: int
    y: int
    width: int
    height: int
    scale: float


def discover_images(root: str | Path) -> list[Path]:
    root_path = Path(root)
    if not root_path.is_dir():
        raise FileNotFoundError(f"image folder not found: {root_path}")
    paths = [
        path
        for path in root_path.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]
    return sorted(paths, key=lambda path: path.name.lower())


def discover_session_zips(root: str | Path) -> list[Path]:
    root_path = Path(root)
    if not root_path.is_dir():
        raise FileNotFoundError(f"session zip folder not found: {root_path}")
    paths = [
        path
        for path in root_path.iterdir()
        if path.is_file() and path.suffix.lower() == ".zip" and path.name.lower().startswith("session_")
    ]
    return sorted(paths, key=lambda path: path.name.lower())


def load_session_zip_folder_images(root: str | Path) -> list[ImageAnnotationRecord]:
    zip_paths = discover_session_zips(root)
    if not zip_paths:
        raise ValueError(f"no session zip files found: {Path(root)}")
    records: list[ImageAnnotationRecord] = []
    for zip_path in zip_paths:
        records.extend(load_session_zip_images(zip_path))
    return records


def load_session_zip_images(zip_path: str | Path) -> list[ImageAnnotationRecord]:
    source_zip = Path(zip_path)
    if not source_zip.is_file():
        raise FileNotFoundError(f"session zip not found: {source_zip}")
    with zipfile.ZipFile(source_zip) as zf:
        frame_members = sorted(
            [
                name
                for name in zf.namelist()
                if is_supported_frame_member(name)
            ],
            key=str.lower,
        )
        if not frame_members:
            raise ValueError(f"no frame images found in session zip: {source_zip}")
        manifest = read_manifest_from_zip(zf, source_zip)
    session_id = str(manifest.get("session_id", ""))
    point_id = str(manifest.get("point_id", ""))
    return [
        ImageAnnotationRecord(
            path=source_zip,
            session_zip_path=source_zip,
            member_name=member,
            session_id=session_id,
            point_id=point_id,
        )
        for member in frame_members
    ]


def is_supported_frame_member(member_name: str) -> bool:
    member_path = PurePosixPath(member_name)
    return (
        not member_name.endswith("/")
        and len(member_path.parts) >= 2
        and member_path.parts[0] == "frames"
        and member_path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    )


def read_manifest_from_zip(zf: zipfile.ZipFile, source_zip: Path) -> dict:
    if "manifest.json" not in zf.namelist():
        return {}
    try:
        return json.loads(zf.read("manifest.json").decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid manifest.json in session zip: {source_zip}") from exc


def make_annotated_name(original_path: str | Path) -> str:
    path = Path(original_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"unsupported image extension: {path}")
    return f"{safe_filename_part(path.stem)}{EXPORT_IMAGE_SUFFIX}"


def make_session_annotated_name(zip_path: str | Path, member_name: str) -> str:
    source_zip = Path(zip_path)
    member_path = PurePosixPath(member_name)
    suffix = member_path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ValueError(f"unsupported image extension: {member_name}")
    return f"{safe_filename_part(source_zip.stem)}__{safe_filename_part(member_path.stem)}{EXPORT_IMAGE_SUFFIX}"


def make_record_annotated_name(record: ImageAnnotationRecord) -> str:
    if record.is_zip_member:
        return make_session_annotated_name(record.session_zip_path, record.member_name)
    return make_annotated_name(record.path)


def safe_filename_part(value: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", value.strip()).strip(" ._")
    if not cleaned:
        raise ValueError("empty filename part")
    return cleaned


def render_annotations(image: Image.Image, annotations: Iterable[Annotation]) -> Image.Image:
    rendered = image.convert("RGBA")
    overlay = Image.new("RGBA", rendered.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for annotation in annotations:
        draw_annotation(draw, annotation)
    rendered.alpha_composite(overlay)
    return rendered.convert(image.mode if image.mode in {"RGB", "L"} else "RGB")


def render_annotation_mask(image_size: tuple[int, int], annotations: Iterable[Annotation]) -> Image.Image:
    mask = Image.new("L", image_size, 0)
    draw = ImageDraw.Draw(mask)
    for annotation in annotations:
        draw_annotation(draw, annotation, fill=255, include_label=False)
    return mask


def draw_annotation(
    draw: ImageDraw.ImageDraw,
    annotation: Annotation,
    fill=None,
    include_label: bool = True,
) -> None:
    color = fill if fill is not None else (*ImageColor.getrgb(annotation.color), 210)
    width = max(1, int(annotation.width))
    if annotation.kind == "cross":
        if len(annotation.coords) != 2:
            raise ValueError("cross annotation requires x,y coordinates")
        x, y = [int(v) for v in annotation.coords]
        radius = max(8, width * 3)
        draw.line((x - radius, y, x + radius, y), fill=color, width=width)
        draw.line((x, y - radius, x, y + radius), fill=color, width=width)
        if include_label and annotation.label:
            draw.text((x + radius + 4, y - radius), annotation.label, fill=color)
        return
    if annotation.kind == "rectangle":
        if len(annotation.coords) != 4:
            raise ValueError("rectangle annotation requires x1,y1,x2,y2 coordinates")
        x1, y1, x2, y2 = normalize_rect(annotation.coords)
        draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
        if include_label and annotation.label:
            draw.text((x1 + 4, y1 + 4), annotation.label, fill=color)
        return
    if annotation.kind == "brush":
        if len(annotation.coords) < 2 or len(annotation.coords) % 2 != 0:
            raise ValueError("brush annotation requires x,y coordinate pairs")
        points = list(zip(annotation.coords[0::2], annotation.coords[1::2]))
        int_points = [(int(x), int(y)) for x, y in points]
        if len(int_points) == 1:
            x, y = int_points[0]
            radius = max(1, width // 2)
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
            return
        draw.line(int_points, fill=color, width=width, joint="curve")
        radius = max(1, width // 2)
        for x, y in int_points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=color)
        return
    raise ValueError(f"unsupported annotation kind: {annotation.kind}")


def normalize_rect(coords: tuple[int, ...]) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [int(v) for v in coords]
    return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)


def calculate_preview_layout(image_size: tuple[int, int], canvas_size: tuple[int, int]) -> PreviewLayout:
    image_width, image_height = image_size
    canvas_width, canvas_height = canvas_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError(f"invalid image size: {image_size}")
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError(f"invalid canvas size: {canvas_size}")
    scale = min(canvas_width / image_width, canvas_height / image_height)
    width = max(1, min(canvas_width, int(round(image_width * scale))))
    height = max(1, min(canvas_height, int(round(image_height * scale))))
    x = max(0, (canvas_width - width) // 2)
    y = max(0, (canvas_height - height) // 2)
    return PreviewLayout(x=x, y=y, width=width, height=height, scale=scale)


def export_annotated_images(
    records: Iterable[ImageAnnotationRecord],
    output_dir: str | Path,
) -> list[ExportMappingRow]:
    output_path = Path(output_dir)
    annotated_records = [record for record in records if record.annotations]
    if not annotated_records:
        raise ValueError("no annotated images to export")
    output_path.mkdir(parents=True, exist_ok=True)
    allowed_entries = {ORIGINAL_IMAGES_DIR, MASKS_DIR}
    unexpected_entries = sorted(path.name for path in output_path.iterdir() if path.name not in allowed_entries)
    if unexpected_entries:
        names = ", ".join(unexpected_entries)
        raise ValueError(f"export directory must be empty or contain only {ORIGINAL_IMAGES_DIR}/{MASKS_DIR}: {names}")

    rows: list[ExportMappingRow] = []
    used_names: set[str] = set()
    originals_path = output_path / ORIGINAL_IMAGES_DIR
    masks_path = output_path / MASKS_DIR
    originals_path.mkdir(parents=True, exist_ok=True)
    masks_path.mkdir(parents=True, exist_ok=True)
    for record in annotated_records:
        export_name = make_record_annotated_name(record)
        if export_name.lower() in used_names:
            raise ValueError(f"duplicate export filename: {export_name}")
        used_names.add(export_name.lower())
        original_export_path = originals_path / export_name
        mask_path = masks_path / export_name
        with record.open_image() as image:
            source_image = image.convert("RGBA") if image.mode == "RGBA" else image.convert("RGB")
            source_image.save(original_export_path)
            mask = render_annotation_mask(image.size, record.annotations)
            mask.save(mask_path)
        rows.append(
            ExportMappingRow(
                original_name=record.original_name,
                export_name=export_name,
                original_path=record.original_path_text,
                original_export_path=original_export_path.resolve(),
                mask_path=mask_path.resolve(),
                annotation_count=len(record.annotations),
                source_type=record.source_type,
                session_zip=record.session_zip_path.name if record.is_zip_member else "",
                session_id=record.session_id,
                point_id=record.point_id,
                original_member=record.member_name,
            )
        )

    return rows


class ImageAnnotationApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.root = root
        self.root.title("Image Annotation Exporter")
        self.records: list[ImageAnnotationRecord] = []
        self.current_index = 0
        self.current_image: Image.Image | None = None
        self.preview_image: Image.Image | None = None
        self.photo: ImageTk.PhotoImage | None = None
        self.display_scale = 1.0
        self.image_offset = (0, 0)
        self.drag_start: tuple[int, int] | None = None
        self.brush_points: list[int] = []

        self.status_var = tk.StringVar(value="打开图片或文件夹开始标注。")
        self.tool_var = tk.StringVar(value="cross")
        self.label_var = tk.StringVar(value="")
        self.color_var = tk.StringVar(value=DEFAULT_COLOR)
        self.width_var = tk.IntVar(value=3)
        self._build_ui(ttk)

    def _build_ui(self, ttk) -> None:
        self.root.geometry("1280x860")
        self.root.minsize(960, 640)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self.root, padding=10)
        sidebar.grid(row=0, column=0, sticky="ns")

        ttk.Button(sidebar, text="打开治疗周期Zip目录", command=self.choose_session_zip_folder).pack(fill="x", pady=(0, 6))
        ttk.Button(sidebar, text="打开治疗周期Zip文件", command=self.choose_session_zip_files).pack(fill="x", pady=(0, 12))
        ttk.Button(sidebar, text="打开图片文件夹", command=self.choose_folder).pack(fill="x", pady=(0, 6))
        ttk.Button(sidebar, text="打开图片文件", command=self.choose_files).pack(fill="x", pady=(0, 12))
        ttk.Label(sidebar, text="标注工具").pack(anchor="w")
        ttk.Radiobutton(sidebar, text="十字点", variable=self.tool_var, value="cross").pack(anchor="w")
        ttk.Radiobutton(sidebar, text="矩形框", variable=self.tool_var, value="rectangle").pack(anchor="w")
        ttk.Radiobutton(sidebar, text="笔刷", variable=self.tool_var, value="brush").pack(anchor="w")
        ttk.Label(sidebar, text="标签（可选）").pack(anchor="w", pady=(10, 0))
        ttk.Entry(sidebar, textvariable=self.label_var, width=22).pack(fill="x")
        ttk.Label(sidebar, text="颜色").pack(anchor="w", pady=(10, 0))
        ttk.Entry(sidebar, textvariable=self.color_var, width=22).pack(fill="x")
        ttk.Label(sidebar, text="线宽").pack(anchor="w", pady=(10, 0))
        ttk.Spinbox(sidebar, from_=1, to=12, textvariable=self.width_var, width=8).pack(anchor="w")
        ttk.Button(sidebar, text="撤销当前图最后一笔", command=self.undo_current).pack(fill="x", pady=(12, 6))
        ttk.Button(sidebar, text="清空当前图标注", command=self.clear_current).pack(fill="x", pady=(0, 12))
        ttk.Button(sidebar, text="导出标注集合", command=self.choose_export_dir).pack(fill="x")

        ttk.Label(sidebar, text="图片列表").pack(anchor="w", pady=(12, 0))
        import tkinter as tk

        self.listbox = tk.Listbox(sidebar, width=34, height=24)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_list_select)

        main = ttk.Frame(self.root, padding=(0, 10, 10, 10))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(main, bg="#111111", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<ButtonPress-1>", self.on_canvas_press)
        self.canvas.bind("<B1-Motion>", self.on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_canvas_release)
        self.canvas.bind("<Configure>", lambda _event: self.refresh_preview())

        status = ttk.Label(main, textvariable=self.status_var, padding=(0, 8, 0, 0))
        status.grid(row=1, column=0, sticky="ew")

    def choose_folder(self) -> None:
        from tkinter import filedialog, messagebox

        folder = filedialog.askdirectory(title="选择图片文件夹")
        if not folder:
            return
        try:
            self.load_paths(discover_images(folder))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def choose_files(self) -> None:
        from tkinter import filedialog, messagebox

        filenames = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=(("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"), ("All files", "*.*")),
        )
        if not filenames:
            return
        try:
            self.load_paths([Path(name) for name in filenames])
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def choose_session_zip_folder(self) -> None:
        from tkinter import filedialog, messagebox

        folder = filedialog.askdirectory(title="选择包含治疗周期Zip的目录")
        if not folder:
            return
        try:
            self.load_records(load_session_zip_folder_images(folder))
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def choose_session_zip_files(self) -> None:
        from tkinter import filedialog, messagebox

        filenames = filedialog.askopenfilenames(
            title="选择治疗周期Zip文件",
            filetypes=(("Session ZIP", "session_*.zip"), ("ZIP files", "*.zip"), ("All files", "*.*")),
        )
        if not filenames:
            return
        try:
            records: list[ImageAnnotationRecord] = []
            for filename in filenames:
                records.extend(load_session_zip_images(filename))
            self.load_records(records)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def load_paths(self, paths: Iterable[Path]) -> None:
        image_paths = [Path(path) for path in paths]
        if not image_paths:
            raise ValueError("no supported images found")
        for path in image_paths:
            if not path.is_file():
                raise FileNotFoundError(f"image not found: {path}")
            if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
                raise ValueError(f"unsupported image extension: {path}")
        self.load_records([ImageAnnotationRecord(path) for path in image_paths])

    def load_records(self, records: Iterable[ImageAnnotationRecord]) -> None:
        loaded_records = list(records)
        if not loaded_records:
            raise ValueError("no supported images found")
        self.records = loaded_records
        self.current_index = 0
        self.refresh_listbox()
        self.load_current_image()

    def refresh_listbox(self) -> None:
        self.listbox.delete(0, "end")
        for record in self.records:
            self.listbox.insert("end", record.display_name)
        if self.records:
            self.listbox.selection_set(self.current_index)

    def on_list_select(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        self.current_index = int(selection[0])
        self.load_current_image()

    def current_record(self) -> ImageAnnotationRecord | None:
        if not self.records:
            return None
        return self.records[self.current_index]

    def load_current_image(self) -> None:
        record = self.current_record()
        if record is None:
            return
        with record.open_image() as image:
            self.current_image = image.convert("RGB")
        self.refresh_preview()
        self.status_var.set(f"{self.current_index + 1}/{len(self.records)} {record.display_name}")

    def refresh_preview(self) -> None:
        record = self.current_record()
        if record is None or self.current_image is None:
            self.canvas.delete("all")
            return
        rendered = render_annotations(self.current_image, record.annotations)
        canvas_width = max(1, int(self.canvas.winfo_width() or PREVIEW_MAX_SIZE[0]))
        canvas_height = max(1, int(self.canvas.winfo_height() or PREVIEW_MAX_SIZE[1]))
        layout = calculate_preview_layout(rendered.size, (canvas_width, canvas_height))
        preview = rendered.resize((layout.width, layout.height), Image.Resampling.LANCZOS)
        self.display_scale = layout.scale
        self.image_offset = (layout.x, layout.y)
        self.preview_image = preview
        self.photo = ImageTk.PhotoImage(preview)
        self.canvas.delete("all")
        self.canvas.create_image(layout.x, layout.y, image=self.photo, anchor="nw")

    def canvas_to_image_point(self, x: float, y: float) -> tuple[int, int]:
        if self.current_image is None:
            raise ValueError("no image loaded")
        scale = self.display_scale if self.display_scale > 0 else 1.0
        offset_x, offset_y = self.image_offset
        image_x = min(self.current_image.width - 1, max(0, int(round((float(x) - offset_x) / scale))))
        image_y = min(self.current_image.height - 1, max(0, int(round((float(y) - offset_y) / scale))))
        return image_x, image_y

    def on_canvas_press(self, event) -> None:
        if self.current_record() is None:
            return
        point = self.canvas_to_image_point(event.x, event.y)
        if self.tool_var.get() == "cross":
            self.add_annotation(Annotation("cross", point, self.color_var.get(), int(self.width_var.get()), self.label_var.get().strip()))
            return
        if self.tool_var.get() == "brush":
            self.brush_points = [point[0], point[1]]
            return
        self.drag_start = point

    def on_canvas_drag(self, event) -> None:
        if self.tool_var.get() != "brush" or not self.brush_points:
            return
        point = self.canvas_to_image_point(event.x, event.y)
        last_x, last_y = self.brush_points[-2], self.brush_points[-1]
        if point == (last_x, last_y):
            return
        self.brush_points.extend([point[0], point[1]])
        self.refresh_preview()
        self.draw_live_brush_preview()

    def on_canvas_release(self, event) -> None:
        if self.tool_var.get() == "brush":
            if not self.brush_points:
                return
            point = self.canvas_to_image_point(event.x, event.y)
            last_x, last_y = self.brush_points[-2], self.brush_points[-1]
            if point != (last_x, last_y):
                self.brush_points.extend([point[0], point[1]])
            coords = tuple(self.brush_points)
            self.brush_points = []
            self.add_annotation(Annotation("brush", coords, self.color_var.get(), int(self.width_var.get()), self.label_var.get().strip()))
            return
        if self.tool_var.get() != "rectangle" or self.drag_start is None:
            return
        end = self.canvas_to_image_point(event.x, event.y)
        x1, y1 = self.drag_start
        x2, y2 = end
        self.drag_start = None
        if x1 == x2 or y1 == y2:
            return
        self.add_annotation(Annotation("rectangle", (x1, y1, x2, y2), self.color_var.get(), int(self.width_var.get()), self.label_var.get().strip()))

    def draw_live_brush_preview(self) -> None:
        if len(self.brush_points) < 4:
            return
        scale = self.display_scale if self.display_scale > 0 else 1.0
        offset_x, offset_y = self.image_offset
        scaled_points = []
        for image_x, image_y in zip(self.brush_points[0::2], self.brush_points[1::2]):
            scaled_points.extend((offset_x + image_x * scale, offset_y + image_y * scale))
        self.canvas.create_line(
            *scaled_points,
            fill=self.color_var.get(),
            width=max(1, int(self.width_var.get()) * scale),
            smooth=True,
            capstyle="round",
            joinstyle="round",
            tags=("live_brush",),
        )

    def add_annotation(self, annotation: Annotation) -> None:
        record = self.current_record()
        if record is None:
            return
        record.annotations.append(annotation)
        self.refresh_preview()
        self.status_var.set(f"已标注：{record.display_name}，当前图 {len(record.annotations)} 个标注")

    def undo_current(self) -> None:
        record = self.current_record()
        if record is None or not record.annotations:
            return
        record.annotations.pop()
        self.refresh_preview()

    def clear_current(self) -> None:
        record = self.current_record()
        if record is None:
            return
        record.annotations.clear()
        self.refresh_preview()

    def choose_export_dir(self) -> None:
        from tkinter import filedialog, messagebox

        folder = filedialog.askdirectory(title="选择导出目录")
        if not folder:
            return
        try:
            rows = export_annotated_images(self.records, folder)
            self.status_var.set(f"导出完成：{len(rows)} 张原图和mask，已生成 original_images / masks")
            messagebox.showinfo("导出完成", f"已导出 {len(rows)} 张原图和 {len(rows)} 张mask。")
        except Exception as exc:
            self.status_var.set(f"导出失败：{exc}")
            messagebox.showerror("导出失败", str(exc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open images, annotate them, and export annotated image collections.")
    parser.add_argument("--folder", help="Optional image folder to load at startup.")
    parser.add_argument("--session-folder", help="Optional folder containing session_*.zip treatment-cycle packages.")
    args = parser.parse_args(argv)

    import tkinter as tk

    root = tk.Tk()
    app = ImageAnnotationApp(root)
    if args.folder and args.session_folder:
        parser.error("--folder and --session-folder cannot be used together")
    if args.folder:
        app.load_paths(discover_images(args.folder))
    if args.session_folder:
        app.load_records(load_session_zip_folder_images(args.session_folder))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
