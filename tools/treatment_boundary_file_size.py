import argparse
import json
import re
import statistics
import sys
from pathlib import Path


METHOD = "file_size"
DEFAULT_BASELINE_COUNT = 6
DEFAULT_SIZE_RATIO_THRESHOLD = 1.5
FRAME_NAME_RE = re.compile(r"^(\d{5})_.*_(before|frame)\.png$")


class BoundaryDetectionError(RuntimeError):
    """Raised when file-size boundary detection cannot produce one result."""


def positive_int(value):
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def positive_float(value):
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive number")
    return parsed


def is_original_sequence_frame(path):
    return FRAME_NAME_RE.match(path.name) is not None


def collect_sequence_frames(folder):
    frames = []
    for path in folder.iterdir():
        if not path.is_file() or not is_original_sequence_frame(path):
            continue
        prefix = int(path.name[:5])
        frames.append(
            {
                "prefix": prefix,
                "name": path.name,
                "path": path,
                "size": path.stat().st_size,
            }
        )
    return sorted(frames, key=lambda frame: (frame["prefix"], frame["name"]))


def find_active_interval(active_flags):
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
            f"expected exactly one continuous active interval, found {len(intervals)}"
        )
    return intervals[0]


def analyze_folder(
    folder,
    baseline_count=DEFAULT_BASELINE_COUNT,
    size_ratio_threshold=DEFAULT_SIZE_RATIO_THRESHOLD,
):
    folder_path = Path(folder).resolve()
    if not folder_path.exists():
        raise BoundaryDetectionError(f"folder does not exist: {folder_path}")
    if not folder_path.is_dir():
        raise BoundaryDetectionError(f"path is not a folder: {folder_path}")
    if baseline_count <= 0:
        raise BoundaryDetectionError("baseline_count must be positive")
    if size_ratio_threshold <= 0:
        raise BoundaryDetectionError("size_ratio_threshold must be positive")

    frames = collect_sequence_frames(folder_path)
    if len(frames) < baseline_count:
        raise BoundaryDetectionError(
            f"need at least {baseline_count} frames for baseline, found {len(frames)}"
        )
    if len(frames) < 3:
        raise BoundaryDetectionError(
            "at least three original sequence frames are required"
        )

    baseline_sizes = [frame["size"] for frame in frames[:baseline_count]]
    baseline_size = statistics.median(baseline_sizes)
    if baseline_size <= 0:
        raise BoundaryDetectionError("baseline_size must be greater than zero")

    active_threshold = baseline_size * size_ratio_threshold
    active_flags = [frame["size"] >= active_threshold for frame in frames]
    active_start, active_end = find_active_interval(active_flags)
    if active_start == 0 or active_end == len(frames) - 1:
        raise BoundaryDetectionError(
            "active interval must have one frame before it and one frame after it"
        )

    return {
        "method": METHOD,
        "folder": str(folder_path),
        "before_frame": frames[active_start - 1]["name"],
        "after_frame": frames[active_end + 1]["name"],
        "active_start_frame": frames[active_start]["name"],
        "active_end_frame": frames[active_end]["name"],
        "frame_count": len(frames),
        "baseline_size": baseline_size,
        "size_ratio_threshold": size_ratio_threshold,
        "baseline_count": baseline_count,
    }


def choose_folder_with_dialog():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(title="Select image folder")
    finally:
        root.destroy()
    if not selected:
        raise BoundaryDetectionError("folder selection was cancelled")
    return Path(selected)


def build_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Detect treatment boundary frames by PNG file-size ratio. "
            "This method is intended only for validation/comparison and is not "
            "recommended as the sole formal algorithm."
        )
    )
    parser.add_argument("--folder", help="Folder containing original sequence PNG frames.")
    parser.add_argument(
        "--baseline-count",
        type=positive_int,
        default=DEFAULT_BASELINE_COUNT,
        help=f"Number of leading frames used for baseline median size. Default: {DEFAULT_BASELINE_COUNT}.",
    )
    parser.add_argument(
        "--size-ratio-threshold",
        type=positive_float,
        default=DEFAULT_SIZE_RATIO_THRESHOLD,
        help=(
            "File-size ratio threshold used to mark active frames. "
            f"Default: {DEFAULT_SIZE_RATIO_THRESHOLD}."
        ),
    )
    return parser


def main(argv=None):
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        folder = Path(args.folder) if args.folder else choose_folder_with_dialog()
        payload = analyze_folder(
            folder,
            baseline_count=args.baseline_count,
            size_ratio_threshold=args.size_ratio_threshold,
        )
    except BoundaryDetectionError as exc:
        print(
            json.dumps({"method": METHOD, "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
