from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image


METHOD = "roi23_gray_threshold"
DEFAULT_BASELINE_COUNT = 6
THRESHOLD_OFFSET = 25.0
FRAME_NAME_RE = re.compile(r"^(\d{5})_.*_(?:before|frame)\.png$")


class BoundaryDetectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoiRect:
    x1: int
    y1: int
    x2: int
    y2: int

    def as_list(self) -> list[int]:
        return [self.x1, self.y1, self.x2, self.y2]


@dataclass(frozen=True)
class FrameMeasurement:
    prefix: int
    path: Path
    roi2_mean: float
    roi3_mean: float


def validate_rect(value: object, name: str) -> RoiRect:
    if not isinstance(value, list) or len(value) != 4:
        raise BoundaryDetectionError(f"{name} must be a list of 4 integers")

    values: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise BoundaryDetectionError(f"{name} must be a list of 4 integers")
        values.append(item)

    x1, y1, x2, y2 = values
    if x1 < 0 or y1 < 0:
        raise BoundaryDetectionError(f"{name} x1 and y1 must be non-negative")
    if x2 <= x1 or y2 <= y1:
        raise BoundaryDetectionError(f"{name} x2/y2 must be greater than x1/y1")
    return RoiRect(x1=x1, y1=y1, x2=x2, y2=y2)


def load_roi_rects(folder: Path) -> tuple[RoiRect, RoiRect]:
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        raise BoundaryDetectionError(f"meta.json is required: {meta_path}")
    if not meta_path.is_file():
        raise BoundaryDetectionError(f"meta.json is not a file: {meta_path}")

    try:
        with meta_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except json.JSONDecodeError as exc:
        raise BoundaryDetectionError(f"meta.json is invalid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise BoundaryDetectionError("meta.json must contain an object")
    if "roi2_rect" not in payload:
        raise BoundaryDetectionError("meta.json missing roi2_rect")
    if "roi3_rect" not in payload:
        raise BoundaryDetectionError("meta.json missing roi3_rect")
    return (
        validate_rect(payload["roi2_rect"], "roi2_rect"),
        validate_rect(payload["roi3_rect"], "roi3_rect"),
    )


def collect_frame_paths(folder: Path) -> list[tuple[int, Path]]:
    if not folder.exists():
        raise BoundaryDetectionError(f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise BoundaryDetectionError(f"folder is not a directory: {folder}")

    matches: list[tuple[int, Path]] = []
    seen_prefixes: dict[int, Path] = {}
    for path in folder.iterdir():
        if not path.is_file():
            continue
        match = FRAME_NAME_RE.match(path.name)
        if match is None:
            continue
        prefix = int(match.group(1))
        if prefix in seen_prefixes:
            raise BoundaryDetectionError(
                f"duplicate frame prefix {prefix:05d}: {seen_prefixes[prefix].name}, {path.name}"
            )
        seen_prefixes[prefix] = path
        matches.append((prefix, path))

    matches.sort(key=lambda item: item[0])
    return matches


def ensure_roi_fits(rect: RoiRect, image_width: int, image_height: int, name: str, path: Path) -> None:
    if rect.x2 > image_width or rect.y2 > image_height:
        raise BoundaryDetectionError(
            f"{name} exceeds image bounds for {path.name}: "
            f"{rect.as_list()} outside {image_width}x{image_height}"
        )


def calculate_roi_means(path: Path, roi2_rect: RoiRect, roi3_rect: RoiRect) -> tuple[float, float]:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        pixels = np.asarray(rgba, dtype=np.float64)[..., :3]

    image_height, image_width = pixels.shape[:2]
    ensure_roi_fits(roi2_rect, image_width, image_height, "roi2_rect", path)
    ensure_roi_fits(roi3_rect, image_width, image_height, "roi3_rect", path)

    gray = (
        (0.299 * pixels[..., 0])
        + (0.587 * pixels[..., 1])
        + (0.114 * pixels[..., 2])
    )
    roi2 = gray[
        roi2_rect.y1 : roi2_rect.y2,
        roi2_rect.x1 : roi2_rect.x2,
    ]
    roi3 = gray[
        roi3_rect.y1 : roi3_rect.y2,
        roi3_rect.x1 : roi3_rect.x2,
    ]
    return float(np.mean(roi2)), float(np.mean(roi3))


def find_single_active_interval(active_flags: list[bool]) -> tuple[int, int]:
    intervals: list[tuple[int, int]] = []
    index = 0
    while index < len(active_flags):
        if not active_flags[index]:
            index += 1
            continue
        start = index
        while index + 1 < len(active_flags) and active_flags[index + 1]:
            index += 1
        intervals.append((start, index))
        index += 1

    if not intervals:
        raise BoundaryDetectionError("no active interval found")
    if len(intervals) != 1:
        raise BoundaryDetectionError(f"expected single active interval, found {len(intervals)}")

    start, end = intervals[0]
    if start == 0:
        raise BoundaryDetectionError("active interval has no frame before it")
    if end == len(active_flags) - 1:
        raise BoundaryDetectionError("active interval has no frame after it")
    return start, end


def analyze_folder(
    folder: str | Path,
    baseline_count: int = DEFAULT_BASELINE_COUNT,
) -> dict[str, object]:
    if baseline_count <= 0:
        raise BoundaryDetectionError(f"baseline_count must be positive: {baseline_count}")

    folder_path = Path(folder).expanduser().resolve()
    frame_paths = collect_frame_paths(folder_path)
    roi2_rect, roi3_rect = load_roi_rects(folder_path)
    if len(frame_paths) < baseline_count:
        raise BoundaryDetectionError(
            f"at least baseline_count frames are required: "
            f"baseline_count={baseline_count}, frame_count={len(frame_paths)}"
        )
    if len(frame_paths) < 3:
        raise BoundaryDetectionError(
            f"at least 3 original sequence frames are required, found {len(frame_paths)}"
        )

    frames: list[FrameMeasurement] = []
    for prefix, path in frame_paths:
        roi2_mean, roi3_mean = calculate_roi_means(path, roi2_rect, roi3_rect)
        frames.append(
            FrameMeasurement(
                prefix=prefix,
                path=path,
                roi2_mean=roi2_mean,
                roi3_mean=roi3_mean,
            )
        )

    baseline2 = float(np.median([frame.roi2_mean for frame in frames[:baseline_count]]))
    baseline3 = float(np.median([frame.roi3_mean for frame in frames[:baseline_count]]))
    threshold2 = baseline2 + THRESHOLD_OFFSET
    threshold3 = baseline3 + THRESHOLD_OFFSET
    active_flags = [
        frame.roi2_mean >= threshold2 and frame.roi3_mean >= threshold3
        for frame in frames
    ]
    active_start, active_end = find_single_active_interval(active_flags)

    return {
        "method": METHOD,
        "folder": str(folder_path),
        "before_frame": frames[active_start - 1].path.name,
        "after_frame": frames[active_end + 1].path.name,
        "active_start_frame": frames[active_start].path.name,
        "active_end_frame": frames[active_end].path.name,
        "frame_count": len(frames),
        "roi2_rect": roi2_rect.as_list(),
        "roi3_rect": roi3_rect.as_list(),
        "baseline_count": int(baseline_count),
        "baseline2": baseline2,
        "baseline3": baseline3,
        "threshold2": threshold2,
        "threshold3": threshold3,
    }


def choose_folder_with_dialog() -> Path:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(title="Select image sequence folder")
    finally:
        root.destroy()
    if not selected:
        raise BoundaryDetectionError("folder selection cancelled")
    return Path(selected)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Detect ROI2/ROI3 treatment boundary frames by gray threshold."
    )
    parser.add_argument("--folder")
    parser.add_argument("--baseline-count", type=int, default=DEFAULT_BASELINE_COUNT)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        folder = Path(args.folder) if args.folder else choose_folder_with_dialog()
        payload = analyze_folder(folder, baseline_count=args.baseline_count)
    except BoundaryDetectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
