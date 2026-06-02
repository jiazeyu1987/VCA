from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image


METHOD = "roi1_full_frame_gray_threshold"
FRAME_NAME_RE = re.compile(r"^(\d{5})_.*_(before|frame)\.png$")
DEFAULT_BASELINE_COUNT = 6
DEFAULT_THRESHOLD_OFFSET = 25.0


class BoundaryDetectionError(RuntimeError):
    pass


def collect_frame_paths(folder: Path) -> list[Path]:
    if not folder.exists():
        raise BoundaryDetectionError(f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise BoundaryDetectionError(f"path is not a folder: {folder}")

    matches: list[tuple[int, Path]] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        match = FRAME_NAME_RE.match(path.name)
        if match is None:
            continue
        matches.append((int(match.group(1)), path))

    if not matches:
        raise BoundaryDetectionError(
            f"no sequence frames matched {FRAME_NAME_RE.pattern} in {folder}"
        )

    matches.sort(key=lambda item: (item[0], item[1].name))
    return [path for _, path in matches]


def calculate_mean_gray(path: Path) -> float:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        pixels = np.asarray(rgba, dtype=np.float64)[..., :3]

    gray = (
        (0.299 * pixels[..., 0])
        + (0.587 * pixels[..., 1])
        + (0.114 * pixels[..., 2])
    )
    return float(np.mean(gray))


def find_single_active_interval(active_flags: list[bool]) -> tuple[int, int]:
    intervals: list[tuple[int, int]] = []
    start: Optional[int] = None

    for index, is_active in enumerate(active_flags):
        if is_active and start is None:
            start = index
        elif not is_active and start is not None:
            intervals.append((start, index - 1))
            start = None

    if start is not None:
        intervals.append((start, len(active_flags) - 1))

    if len(intervals) != 1:
        raise BoundaryDetectionError(
            f"expected exactly one active interval, found {len(intervals)}"
        )

    active_start, active_end = intervals[0]
    if active_start == 0:
        raise BoundaryDetectionError("active interval has no preceding boundary frame")
    if active_end == len(active_flags) - 1:
        raise BoundaryDetectionError("active interval has no following boundary frame")

    return active_start, active_end


def analyze_folder(
    folder: str | Path,
    baseline_count: int = DEFAULT_BASELINE_COUNT,
    threshold_offset: float = DEFAULT_THRESHOLD_OFFSET,
) -> dict[str, object]:
    if baseline_count <= 0:
        raise BoundaryDetectionError("baseline_count must be greater than 0")

    folder_path = Path(folder).expanduser().resolve()
    frames = collect_frame_paths(folder_path)
    if len(frames) < baseline_count:
        raise BoundaryDetectionError(
            f"need at least {baseline_count} frames for baseline, found {len(frames)}"
        )

    mean_grays = [calculate_mean_gray(path) for path in frames]
    baseline_values = np.asarray(mean_grays[:baseline_count], dtype=np.float64)
    baseline = float(np.median(baseline_values))
    active_threshold = float(baseline + threshold_offset)
    active_flags = [mean_gray >= active_threshold for mean_gray in mean_grays]
    active_start, active_end = find_single_active_interval(active_flags)

    return {
        "method": METHOD,
        "folder": str(folder_path),
        "before_frame": frames[active_start - 1].name,
        "after_frame": frames[active_end + 1].name,
        "active_start_frame": frames[active_start].name,
        "active_end_frame": frames[active_end].name,
        "frame_count": len(frames),
        "baseline": baseline,
        "baseline_count": baseline_count,
        "threshold_offset": float(threshold_offset),
        "active_threshold": active_threshold,
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
        description="Detect treatment boundary frames with ROI1 full-frame gray thresholding."
    )
    parser.add_argument("--folder", help="Folder containing PNG sequence frames.")
    parser.add_argument(
        "--baseline-count",
        type=int,
        default=DEFAULT_BASELINE_COUNT,
        help=f"Number of initial frames used for baseline. Default: {DEFAULT_BASELINE_COUNT}.",
    )
    parser.add_argument(
        "--threshold-offset",
        type=float,
        default=DEFAULT_THRESHOLD_OFFSET,
        help=(
            "Offset added to the baseline mean gray value for active-frame detection. "
            f"Default: {DEFAULT_THRESHOLD_OFFSET}."
        ),
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        folder = Path(args.folder) if args.folder else choose_folder_with_dialog()
        payload = analyze_folder(
            folder,
            baseline_count=args.baseline_count,
            threshold_offset=args.threshold_offset,
        )
    except BoundaryDetectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
