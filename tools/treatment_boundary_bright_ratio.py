import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image


FRAME_NAME_RE = re.compile(r"^(\d{5})_.*_(before|frame)\.png$")
DEFAULT_BASELINE_COUNT = 6
DEFAULT_ACTIVE_RATIO_THRESHOLD = 0.20
BRIGHT_THRESHOLD_OFFSET = 25.0


class BoundaryDetectionError(Exception):
    pass


def collect_sequence_frames(folder):
    folder_path = Path(folder).expanduser().resolve()
    if not folder_path.exists():
        raise BoundaryDetectionError(f"folder does not exist: {folder_path}")
    if not folder_path.is_dir():
        raise BoundaryDetectionError(f"path is not a folder: {folder_path}")

    frames = []
    for entry in folder_path.iterdir():
        if not entry.is_file():
            continue
        match = FRAME_NAME_RE.match(entry.name)
        if match:
            frames.append((int(match.group(1)), entry))

    if not frames:
        raise BoundaryDetectionError(
            f"no sequence frames matched {FRAME_NAME_RE.pattern} in {folder_path}"
        )

    return [entry for _, entry in sorted(frames, key=lambda item: (item[0], item[1].name))]


def image_gray_array(path):
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        pixels = np.asarray(rgba, dtype=np.float64)[..., :3]

    return (
        (0.299 * pixels[..., 0])
        + (0.587 * pixels[..., 1])
        + (0.114 * pixels[..., 2])
    )


def find_single_active_interval(active_flags):
    intervals = []
    start = None
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
    folder,
    baseline_count=DEFAULT_BASELINE_COUNT,
    active_ratio_threshold=DEFAULT_ACTIVE_RATIO_THRESHOLD,
):
    if baseline_count <= 0:
        raise BoundaryDetectionError("baseline_count must be greater than 0")
    if active_ratio_threshold < 0.0 or active_ratio_threshold > 1.0:
        raise BoundaryDetectionError("active_ratio_threshold must be between 0.0 and 1.0")

    folder_path = Path(folder).expanduser().resolve()
    frames = collect_sequence_frames(folder_path)
    if len(frames) < baseline_count:
        raise BoundaryDetectionError(
            f"need at least {baseline_count} frames for baseline, found {len(frames)}"
        )

    gray_frames = [image_gray_array(path) for path in frames]
    baseline_means = [float(np.mean(gray)) for gray in gray_frames[:baseline_count]]
    baseline = float(np.median(np.asarray(baseline_means, dtype=np.float64)))
    bright_threshold = baseline + BRIGHT_THRESHOLD_OFFSET
    bright_ratios = [
        float(np.mean(gray >= bright_threshold))
        for gray in gray_frames
    ]
    active_flags = [
        ratio >= active_ratio_threshold
        for ratio in bright_ratios
    ]
    active_start, active_end = find_single_active_interval(active_flags)

    return {
        "method": "bright_ratio",
        "folder": str(folder_path),
        "before_frame": frames[active_start - 1].name,
        "after_frame": frames[active_end + 1].name,
        "active_start_frame": frames[active_start].name,
        "active_end_frame": frames[active_end].name,
        "frame_count": len(frames),
        "bright_threshold": bright_threshold,
        "active_ratio_threshold": active_ratio_threshold,
        "baseline": baseline,
        "baseline_count": baseline_count,
    }


def choose_folder():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(title="Select image sequence folder")
    finally:
        root.destroy()

    if not selected:
        raise BoundaryDetectionError("no folder selected")
    return selected


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Detect treatment boundary frames with the bright pixel ratio method."
    )
    parser.add_argument("--folder", help="Folder containing PNG sequence frames.")
    parser.add_argument(
        "--baseline-count",
        type=int,
        default=DEFAULT_BASELINE_COUNT,
        help=f"Number of initial frames used for the baseline. Default: {DEFAULT_BASELINE_COUNT}.",
    )
    parser.add_argument(
        "--active-ratio-threshold",
        type=float,
        default=DEFAULT_ACTIVE_RATIO_THRESHOLD,
        help=(
            "Minimum bright-pixel ratio for an active frame. "
            f"Default: {DEFAULT_ACTIVE_RATIO_THRESHOLD}."
        ),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    folder = args.folder if args.folder else choose_folder()
    payload = analyze_folder(
        folder,
        baseline_count=args.baseline_count,
        active_ratio_threshold=args.active_ratio_threshold,
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BoundaryDetectionError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
