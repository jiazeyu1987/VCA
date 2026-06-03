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


METHOD = "frame_delta"
DEFAULT_MIN_JUMP = 10.0
FRAME_NAME_RE = re.compile(r"^(\d{5})_.*_(?:before|frame)\.png$")


class BoundaryDetectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class FrameMeasurement:
    prefix: int
    path: Path
    mean_gray: float


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


def analyze_folder(folder: str | Path, min_jump: float = DEFAULT_MIN_JUMP) -> dict[str, object]:
    if min_jump <= 0:
        raise BoundaryDetectionError(f"min_jump must be positive: {min_jump}")

    folder_path = Path(folder).expanduser().resolve()
    frame_paths = collect_frame_paths(folder_path)
    if len(frame_paths) < 3:
        raise BoundaryDetectionError(
            f"at least 3 original sequence frames are required, found {len(frame_paths)}"
        )

    frames = [
        FrameMeasurement(prefix=prefix, path=path, mean_gray=calculate_mean_gray(path))
        for prefix, path in frame_paths
    ]
    deltas = [
        frames[index + 1].mean_gray - frames[index].mean_gray
        for index in range(len(frames) - 1)
    ]

    start_index = max(range(len(deltas)), key=lambda index: deltas[index])
    end_index = min(range(len(deltas)), key=lambda index: deltas[index])
    start_delta = float(deltas[start_index])
    end_delta = float(deltas[end_index])

    if start_delta < min_jump:
        raise BoundaryDetectionError(
            f"start_delta {start_delta:.6g} is below min_jump {min_jump:.6g}"
        )
    if end_delta > -min_jump:
        raise BoundaryDetectionError(
            f"end_delta {end_delta:.6g} is above negative min_jump {-min_jump:.6g}"
        )
    if start_index >= end_index:
        raise BoundaryDetectionError(
            "start_transition must occur before end_transition"
        )

    return {
        "method": METHOD,
        "folder": str(folder_path),
        "before_frame": frames[start_index].path.name,
        "after_frame": frames[end_index + 1].path.name,
        "active_start_frame": frames[start_index + 1].path.name,
        "active_end_frame": frames[end_index].path.name,
        "frame_count": len(frames),
        "start_delta": start_delta,
        "end_delta": end_delta,
        "min_jump": float(min_jump),
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
        description="Detect treatment boundary frames by adjacent frame mean-gray deltas."
    )
    parser.add_argument("--folder")
    parser.add_argument("--min-jump", type=float, default=DEFAULT_MIN_JUMP)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        folder = Path(args.folder) if args.folder else choose_folder_with_dialog()
        payload = analyze_folder(folder, min_jump=args.min_jump)
    except BoundaryDetectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
