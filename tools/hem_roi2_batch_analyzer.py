import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image


PYWRAPPER_DIR = Path(__file__).resolve().parents[1] / "resource" / "pywrapper"
if str(PYWRAPPER_DIR) not in sys.path:
    sys.path.insert(0, str(PYWRAPPER_DIR))

import api_server


SUMMARY_FIELDS = [
    "sequence",
    "status",
    "error",
    "frame_count",
    "focus_anchor",
    "offset_anchor",
    "roi2_rect",
    "before_frame_index",
    "before_frame",
    "before_mean",
    "after_frame_index",
    "after_frame",
    "after_mean",
    "roi2_diff",
    "difference_threshold",
    "roi2_color",
    "after_strategy",
]

FRAME_FIELDS = [
    "sequence",
    "frame_index",
    "frame",
    "roi2_mean",
    "roi2_diff_from_before",
]


@dataclass(frozen=True)
class AnalyzerConfig:
    root_dir: Path
    output_csv: Path
    per_frame_csv: Optional[Path]
    settings_path: Optional[Path]
    focus_point: Any
    focus_points_csv: Optional[Path]
    provider_depth_mm: Optional[float]
    focus_y_offset_mm: float
    roi2_extension_params: dict
    difference_threshold: float
    before_frame_index: int
    after_strategy: str
    include_selected_debug: bool
    max_sequences: Optional[int]


def _fmt_float(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{float(value):.6f}"


def _fmt_point(value: Optional[tuple[int, int]]) -> str:
    if value is None:
        return ""
    return f"{int(value[0])},{int(value[1])}"


def _fmt_rect(value: Optional[tuple[int, int, int, int]]) -> str:
    if value is None:
        return ""
    return ",".join(str(int(v)) for v in value)


def _parse_focus_point_value(value: Any) -> Optional[tuple[int, int]]:
    if value is None or value == "":
        return None
    if isinstance(value, (list, tuple)):
        if len(value) != 2:
            raise ValueError(f"focus_point list must contain exactly two values, got {value!r}")
        return int(value[0]), int(value[1])
    return api_server.parse_focus_point(value)


def _load_settings(path: Optional[Path]) -> dict:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"settings file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"settings file must contain a JSON object: {path}")
    return payload


def _settings_roi2_params(settings: dict) -> dict:
    peak = settings.get("peak_detect")
    if not isinstance(peak, dict):
        return {"left": 40, "right": 40, "top": 50, "bottom": 30}
    roi2 = peak.get("roi2_extension_params")
    if roi2 is None:
        return {"left": 40, "right": 40, "top": 50, "bottom": 30}
    if not isinstance(roi2, dict):
        raise ValueError("settings.peak_detect.roi2_extension_params must be an object")
    return dict(roi2)


def _settings_difference_threshold(settings: dict) -> float:
    peak = settings.get("peak_detect")
    if not isinstance(peak, dict):
        return 0.5
    threshold = peak.get("difference_threshold", 0.5)
    return float(threshold)


def _settings_focus_y_offset(settings: dict) -> float:
    focus_guides = settings.get("focus_guides")
    if not isinstance(focus_guides, dict):
        return 0.0
    return api_server.validate_focus_y_offset_mm(focus_guides.get("y_offset_mm", 0.0))


def _parse_roi2_params(text: Optional[str], settings: dict) -> dict:
    if not text:
        return _settings_roi2_params(settings)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("--roi2-extension-params must be JSON, e.g. {\"left\":40,\"right\":40,\"top\":50,\"bottom\":30}") from exc
    if not isinstance(payload, dict):
        raise ValueError("--roi2-extension-params must be a JSON object")
    for key in ("left", "right", "top", "bottom"):
        if key not in payload:
            raise ValueError(f"--roi2-extension-params missing key: {key}")
    return payload


def load_focus_points_csv(path: Optional[Path]) -> dict[str, Any]:
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"focus points CSV not found: {path}")
    result: dict[str, Any] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        required = {"sequence", "focus_point"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"focus points CSV missing columns: {', '.join(sorted(missing))}")
        for row in reader:
            sequence = (row.get("sequence") or "").strip()
            focus_point = (row.get("focus_point") or "").strip()
            if sequence and focus_point:
                result[sequence] = focus_point
    return result


def list_sequences(root_dir: Path, max_sequences: Optional[int]) -> list[Path]:
    if not root_dir.exists():
        raise FileNotFoundError(f"root directory not found: {root_dir}")
    if not root_dir.is_dir():
        raise NotADirectoryError(f"root path is not a directory: {root_dir}")
    sequences = sorted([p for p in root_dir.iterdir() if p.is_dir()], key=lambda p: p.name)
    if max_sequences is not None:
        return sequences[: int(max_sequences)]
    return sequences


def list_frame_paths(sequence_dir: Path, include_selected_debug: bool) -> list[Path]:
    frames = []
    raw_frame_pattern = re.compile(r"^\d+_.*_frame\.png$", re.IGNORECASE)
    for path in sequence_dir.iterdir():
        if not path.is_file() or path.suffix.lower() != ".png":
            continue
        is_raw_frame = bool(raw_frame_pattern.match(path.name))
        is_selected_debug = path.name.lower().startswith("selected_")
        if not is_raw_frame and not (include_selected_debug and is_selected_debug):
            continue
        frames.append(path)
    return sorted(frames, key=lambda p: p.name)


def load_frame(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def frame_roi2_mean(path: Path, roi2_rect: tuple[int, int, int, int]) -> float:
    frame = load_frame(path)
    return api_server.roi_gray_mean(frame, roi2_rect)


def resolve_sequence_focus(sequence_name: str, config: AnalyzerConfig, focus_points: dict[str, Any]) -> tuple[int, int]:
    raw_focus = focus_points.get(sequence_name, config.focus_point)
    anchor = _parse_focus_point_value(raw_focus)
    if anchor is None:
        raise ValueError(f"focus_point is required for sequence {sequence_name}")
    return anchor


def resolve_roi2_rect(
    first_frame: np.ndarray,
    anchor: tuple[int, int],
    config: AnalyzerConfig,
) -> tuple[tuple[int, int], tuple[int, int, int, int]]:
    height, width = first_frame.shape[:2]
    offline_config = api_server.OfflineConfig(
        roi2_extension_params=dict(config.roi2_extension_params),
        focus_y_offset_mm=float(config.focus_y_offset_mm),
    )
    offset_anchor = api_server.resolve_offset_focus_anchor(
        (width, height),
        anchor,
        config.provider_depth_mm,
        offline_config,
    )
    roi2_rect = api_server.compute_roi_region(
        (width, height),
        offset_anchor,
        config.roi2_extension_params,
    )
    if roi2_rect is None:
        raise ValueError(
            "ROI2 rectangle is outside image bounds "
            f"sequence_size={(width, height)} focus={anchor} offset_anchor={offset_anchor} params={config.roi2_extension_params}"
        )
    return offset_anchor, roi2_rect


def choose_after_index(frame_means: list[float], before_index_zero_based: int, strategy: str) -> int:
    if not frame_means:
        raise ValueError("frame_means is empty")
    if strategy == "last":
        return len(frame_means) - 1
    if strategy == "roi2_peak":
        candidates = range(before_index_zero_based + 1, len(frame_means))
        best_index = None
        best_mean = None
        for index in candidates:
            mean = frame_means[index]
            if best_mean is None or mean > best_mean:
                best_index = index
                best_mean = mean
        if best_index is None:
            raise ValueError("after_strategy=roi2_peak requires at least one frame after before_frame_index")
        return best_index
    raise ValueError(f"unsupported after_strategy: {strategy}")


def analyze_sequence(
    sequence_dir: Path,
    config: AnalyzerConfig,
    focus_points: dict[str, Any],
) -> tuple[dict[str, str], list[dict[str, str]]]:
    frame_paths = list_frame_paths(sequence_dir, config.include_selected_debug)
    if not frame_paths:
        raise ValueError(f"sequence has no PNG frames: {sequence_dir}")
    before_index = int(config.before_frame_index) - 1
    if before_index < 0 or before_index >= len(frame_paths):
        raise ValueError(
            f"before_frame_index out of range for sequence {sequence_dir.name}: "
            f"{config.before_frame_index} not in 1..{len(frame_paths)}"
        )
    focus_anchor = resolve_sequence_focus(sequence_dir.name, config, focus_points)
    first_frame = load_frame(frame_paths[before_index])
    offset_anchor, roi2_rect = resolve_roi2_rect(first_frame, focus_anchor, config)

    frame_means = [frame_roi2_mean(path, roi2_rect) for path in frame_paths]
    before_mean = frame_means[before_index]
    after_index = choose_after_index(frame_means, before_index, config.after_strategy)
    after_mean = frame_means[after_index]
    roi2_diff = float(after_mean) - float(before_mean)
    roi2_color = "green" if roi2_diff >= float(config.difference_threshold) else "red"

    row = {
        "sequence": sequence_dir.name,
        "status": "ok",
        "error": "",
        "frame_count": str(len(frame_paths)),
        "focus_anchor": _fmt_point(focus_anchor),
        "offset_anchor": _fmt_point(offset_anchor),
        "roi2_rect": _fmt_rect(roi2_rect),
        "before_frame_index": str(before_index + 1),
        "before_frame": frame_paths[before_index].name,
        "before_mean": _fmt_float(before_mean),
        "after_frame_index": str(after_index + 1),
        "after_frame": frame_paths[after_index].name,
        "after_mean": _fmt_float(after_mean),
        "roi2_diff": _fmt_float(roi2_diff),
        "difference_threshold": _fmt_float(config.difference_threshold),
        "roi2_color": roi2_color,
        "after_strategy": config.after_strategy,
    }
    frame_rows = []
    for index, path in enumerate(frame_paths):
        frame_rows.append(
            {
                "sequence": sequence_dir.name,
                "frame_index": str(index + 1),
                "frame": path.name,
                "roi2_mean": _fmt_float(frame_means[index]),
                "roi2_diff_from_before": _fmt_float(float(frame_means[index]) - float(before_mean)),
            }
        )
    return row, frame_rows


def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def analyze_root(config: AnalyzerConfig) -> list[dict[str, str]]:
    focus_points = load_focus_points_csv(config.focus_points_csv)
    summary_rows: list[dict[str, str]] = []
    frame_rows: list[dict[str, str]] = []
    for sequence_dir in list_sequences(config.root_dir, config.max_sequences):
        row, sequence_frame_rows = analyze_sequence(sequence_dir, config, focus_points)
        summary_rows.append(row)
        frame_rows.extend(sequence_frame_rows)
    write_csv(config.output_csv, SUMMARY_FIELDS, summary_rows)
    if config.per_frame_csv is not None:
        write_csv(config.per_frame_csv, FRAME_FIELDS, frame_rows)
    return summary_rows


def build_config_from_args(argv: Optional[list[str]] = None) -> AnalyzerConfig:
    parser = argparse.ArgumentParser(description="Batch analyze HEM ROI2 gray-difference metrics for treatment sequences.")
    parser.add_argument("--root", required=True, help="Root directory containing one treatment sequence per child folder.")
    parser.add_argument("--output-csv", required=True, help="Summary CSV output path.")
    parser.add_argument("--per-frame-csv", help="Optional per-frame ROI2 metric CSV output path.")
    parser.add_argument("--settings", default="settings", help="Settings JSON path used for default ROI2 params and thresholds.")
    parser.add_argument("--focus-point", help='Global focus point, e.g. "PointF(434.85052, 272.8398)" or "434,272".')
    parser.add_argument("--focus-points-csv", help="Optional CSV with columns: sequence,focus_point.")
    parser.add_argument("--provider-depth-mm", type=float, help="Provider ultrasound depth in mm, required when focus_y_offset_mm > 0.")
    parser.add_argument("--focus-y-offset-mm", type=float, help="Override focus_guides.y_offset_mm from settings.")
    parser.add_argument("--roi2-extension-params", help='Override ROI2 params as JSON, e.g. {"left":40,"right":40,"top":50,"bottom":30}.')
    parser.add_argument("--difference-threshold", type=float, help="Override ROI2 green threshold.")
    parser.add_argument("--before-frame-index", type=int, default=1, help="1-based before/baseline frame index. Default: 1.")
    parser.add_argument("--after-strategy", choices=["roi2_peak", "last"], default="roi2_peak", help="After frame selection strategy.")
    parser.add_argument("--include-selected-debug", action="store_true", help="Include selected_*.png debug images in frame analysis.")
    parser.add_argument("--max-sequences", type=int, help="Limit analyzed sequence count for smoke runs.")
    args = parser.parse_args(argv)

    settings_path = Path(args.settings) if args.settings else None
    settings = _load_settings(settings_path) if settings_path is not None else {}
    focus_y_offset = (
        api_server.validate_focus_y_offset_mm(args.focus_y_offset_mm)
        if args.focus_y_offset_mm is not None
        else _settings_focus_y_offset(settings)
    )
    roi2_params = _parse_roi2_params(args.roi2_extension_params, settings)
    difference_threshold = (
        float(args.difference_threshold)
        if args.difference_threshold is not None
        else _settings_difference_threshold(settings)
    )
    return AnalyzerConfig(
        root_dir=Path(args.root),
        output_csv=Path(args.output_csv),
        per_frame_csv=Path(args.per_frame_csv) if args.per_frame_csv else None,
        settings_path=settings_path,
        focus_point=args.focus_point,
        focus_points_csv=Path(args.focus_points_csv) if args.focus_points_csv else None,
        provider_depth_mm=args.provider_depth_mm,
        focus_y_offset_mm=focus_y_offset,
        roi2_extension_params=roi2_params,
        difference_threshold=difference_threshold,
        before_frame_index=int(args.before_frame_index),
        after_strategy=args.after_strategy,
        include_selected_debug=bool(args.include_selected_debug),
        max_sequences=args.max_sequences,
    )


def main(argv: Optional[list[str]] = None) -> int:
    config = build_config_from_args(argv)
    rows = analyze_root(config)
    print(f"analyzed_sequences={len(rows)}")
    print(f"summary_csv={config.output_csv}")
    if config.per_frame_csv is not None:
        print(f"per_frame_csv={config.per_frame_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
