import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image


FRAME_PATTERN = re.compile(r"^(\d{5})_.*_(before|frame)\.png$")
DEFAULT_THRESHOLD_OFFSET = 25.0
DEFAULT_END_DIFF_THRESHOLD = 7.0


class BoundaryDetectionError(Exception):
    pass


@dataclass(frozen=True)
class SequenceFrame:
    index: int
    name: str
    path: Path
    mean: float


def calculate_gray_mean(path):
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.float64)
    except OSError as exc:
        raise BoundaryDetectionError(f"failed to read image {path}: {exc}") from exc

    gray = (0.299 * rgb[:, :, 0]) + (0.587 * rgb[:, :, 1]) + (0.114 * rgb[:, :, 2])
    return float(np.mean(gray))


def load_sequence_frames(folder):
    folder = Path(folder)
    if not folder.exists():
        raise BoundaryDetectionError(f"folder does not exist: {folder}")
    if not folder.is_dir():
        raise BoundaryDetectionError(f"path is not a folder: {folder}")

    candidates = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        match = FRAME_PATTERN.match(path.name)
        if match is None:
            continue
        candidates.append((int(match.group(1)), path.name, path))

    if not candidates:
        raise BoundaryDetectionError(
            "no raw sequence frames found; expected filenames matching "
            r"^\d{5}_.*_(before|frame)\.png$"
        )

    frames = []
    for index, _name, path in sorted(candidates, key=lambda item: (item[0], item[1])):
        frames.append(
            SequenceFrame(
                index=index,
                name=path.name,
                path=path,
                mean=calculate_gray_mean(path),
            )
        )
    return frames


def analyze_folder(
    folder,
    threshold_offset=DEFAULT_THRESHOLD_OFFSET,
    end_diff_threshold=DEFAULT_END_DIFF_THRESHOLD,
):
    frames = load_sequence_frames(folder)
    before_baseline = frames[0].mean
    high_threshold = before_baseline + float(threshold_offset)
    end_diff_threshold = float(end_diff_threshold)

    state = "low"
    previous_frame = None
    before_frame = None
    after_frame = None
    active_start_frame = None
    active_end_frame = None

    for frame in frames:
        if state == "low":
            if frame.mean >= high_threshold:
                if previous_frame is None:
                    raise BoundaryDetectionError(
                        "could not determine before_frame: active state started on the first frame"
                    )
                before_frame = previous_frame.name
                active_start_frame = frame.name
                state = "active"
        elif abs(frame.mean - before_baseline) <= end_diff_threshold:
            if previous_frame is None:
                raise BoundaryDetectionError(
                    "could not determine active_end_frame before after_frame"
                )
            active_end_frame = previous_frame.name
            after_frame = frame.name
            break

        previous_frame = frame

    if active_start_frame is None or before_frame is None:
        raise BoundaryDetectionError(
            "could not determine active_start_frame/before_frame: no frame reached high_threshold"
        )
    if after_frame is None or active_end_frame is None:
        raise BoundaryDetectionError(
            "could not determine after_frame: active state never returned to baseline"
        )

    return {
        "method": "peak_state",
        "folder": str(Path(folder).resolve()),
        "before_frame": before_frame,
        "after_frame": after_frame,
        "active_start_frame": active_start_frame,
        "active_end_frame": active_end_frame,
        "frame_count": len(frames),
        "high_threshold": high_threshold,
        "end_diff_threshold": end_diff_threshold,
    }


def ask_folder():
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as exc:
        raise BoundaryDetectionError(f"tkinter is required when --folder is omitted: {exc}") from exc

    root = tk.Tk()
    root.withdraw()
    try:
        return filedialog.askdirectory()
    finally:
        root.destroy()


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Detect treatment boundary frames with a peak-state machine."
    )
    parser.add_argument("--folder", help="Folder containing raw sequence PNG frames.")
    parser.add_argument(
        "--threshold-offset",
        type=float,
        default=DEFAULT_THRESHOLD_OFFSET,
        help="Offset added to the first-frame baseline to enter active state.",
    )
    parser.add_argument(
        "--end-diff-threshold",
        type=float,
        default=DEFAULT_END_DIFF_THRESHOLD,
        help="Maximum absolute mean difference from baseline to exit active state.",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    folder = args.folder
    if folder is None:
        folder = ask_folder()
        if not folder:
            print("folder selection cancelled", file=sys.stderr)
            return 1

    try:
        result = analyze_folder(
            folder,
            threshold_offset=args.threshold_offset,
            end_diff_threshold=args.end_diff_threshold,
        )
    except BoundaryDetectionError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
