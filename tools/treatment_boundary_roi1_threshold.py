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
DEFAULT_MAX_INACTIVE_GAP = 1
DEFAULT_ACTIVE_EXTENSION_OFFSET = 9.0
DEFAULT_RETURN_TO_BASELINE_OFFSET = 5.0
DEFAULT_BOUNDARY_OFFSET = 2


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


def find_single_active_interval(
    active_flags: list[bool],
    max_inactive_gap: int = DEFAULT_MAX_INACTIVE_GAP,
) -> tuple[int, int]:
    if max_inactive_gap < 0:
        raise BoundaryDetectionError("max_inactive_gap must be greater than or equal to 0")

    intervals: list[tuple[int, int]] = []
    start: Optional[int] = None
    inactive_run = 0

    for index, is_active in enumerate(active_flags):
        if is_active and start is None:
            start = index
            inactive_run = 0
        elif is_active and start is not None:
            inactive_run = 0
        elif not is_active and start is not None:
            inactive_run += 1
            if inactive_run > max_inactive_gap:
                intervals.append((start, index - inactive_run))
                start = None
                inactive_run = 0

    if start is not None:
        tail_trim = inactive_run if inactive_run > 0 else 0
        intervals.append((start, len(active_flags) - 1 - tail_trim))

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
    max_inactive_gap: int = DEFAULT_MAX_INACTIVE_GAP,
    active_extension_offset: float = DEFAULT_ACTIVE_EXTENSION_OFFSET,
    return_to_baseline_offset: float = DEFAULT_RETURN_TO_BASELINE_OFFSET,
    boundary_offset: int = DEFAULT_BOUNDARY_OFFSET,
) -> dict[str, object]:
    if baseline_count <= 0:
        raise BoundaryDetectionError("baseline_count must be greater than 0")
    if boundary_offset <= 0:
        raise BoundaryDetectionError("boundary_offset must be greater than 0")

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
    active_extension_threshold = float(baseline + active_extension_offset)
    return_to_baseline_threshold = float(baseline + return_to_baseline_offset)
    active_flags = [mean_gray >= active_threshold for mean_gray in mean_grays]
    active_start, active_end = find_single_active_interval(active_flags, max_inactive_gap=max_inactive_gap)

    while active_start > 0 and mean_grays[active_start - 1] >= active_extension_threshold:
        active_start -= 1
    while active_end + 1 < len(mean_grays) and mean_grays[active_end + 1] >= return_to_baseline_threshold:
        active_end += 1
    before_index = active_start - int(boundary_offset)
    after_index = active_end + int(boundary_offset)
    after_fallback_used = False
    if before_index < 0:
        raise BoundaryDetectionError(
            f"active interval does not have boundary frame offset {boundary_offset} before it"
        )
    if after_index >= len(frames):
        after_index = len(frames) - 1
        after_fallback_used = True

    return {
        "method": METHOD,
        "folder": str(folder_path),
        "before_frame": frames[before_index].name,
        "after_frame": frames[after_index].name,
        "active_start_frame": frames[active_start].name,
        "active_end_frame": frames[active_end].name,
        "frame_count": len(frames),
        "baseline": baseline,
        "baseline_count": baseline_count,
        "threshold_offset": float(threshold_offset),
        "max_inactive_gap": int(max_inactive_gap),
        "active_threshold": active_threshold,
        "active_extension_offset": float(active_extension_offset),
        "active_extension_threshold": active_extension_threshold,
        "return_to_baseline_offset": float(return_to_baseline_offset),
        "return_to_baseline_threshold": return_to_baseline_threshold,
        "boundary_offset": int(boundary_offset),
        "after_fallback_used": bool(after_fallback_used),
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
    parser.add_argument(
        "--max-inactive-gap",
        type=int,
        default=DEFAULT_MAX_INACTIVE_GAP,
        help=(
            "Maximum number of consecutive inactive frames allowed inside one active interval. "
            f"Default: {DEFAULT_MAX_INACTIVE_GAP}."
        ),
    )
    parser.add_argument(
        "--active-extension-offset",
        type=float,
        default=DEFAULT_ACTIVE_EXTENSION_OFFSET,
        help=(
            "Additional gray-mean offset above baseline used to extend the active interval backward "
            f"before the peak core. Default: {DEFAULT_ACTIVE_EXTENSION_OFFSET}."
        ),
    )
    parser.add_argument(
        "--return-to-baseline-offset",
        type=float,
        default=DEFAULT_RETURN_TO_BASELINE_OFFSET,
        help=(
            "Maximum gray-mean offset above baseline that marks the return to baseline after treatment. "
            f"Default: {DEFAULT_RETURN_TO_BASELINE_OFFSET}."
        ),
    )
    parser.add_argument(
        "--boundary-offset",
        type=int,
        default=DEFAULT_BOUNDARY_OFFSET,
        help=(
            "Number of raw sequence frames to step outside the detected active interval for before/after selection. "
            f"Default: {DEFAULT_BOUNDARY_OFFSET}."
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
            max_inactive_gap=args.max_inactive_gap,
            active_extension_offset=args.active_extension_offset,
            return_to_baseline_offset=args.return_to_baseline_offset,
            boundary_offset=args.boundary_offset,
        )
    except BoundaryDetectionError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
