# -*- coding: utf-8 -*-
import argparse
import ctypes
import errno
import json
import logging
import math
import os
import re
import sqlite3
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageGrab


PASSWORD = "31415"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30415
DEVICE_RECONNECT_FAILED_EXIT_CODE = 70
ONLINE_PROVIDER_TIMEOUT_SECONDS = 3.0
ONLINE_RECONNECT_TIMEOUT_SECONDS = 2.0
EXTERNAL_RUNTIME_DIR = Path(r"D:\ocr3\resource\pywrapper")
REQUIRED_RUNTIME_FILES = (
    "PyMobileComm.pyd",
    "MobileCommunication.dll",
    "DicomContol_Factory.dll",
    "AdbWinApi.dll",
    "AdbWinUsbApi.dll",
    "Company.ini",
    "license",
)
PROVIDER_FIELDS = (
    "focus_depth",
    "guankuan_a",
    "guankuan_b",
    "depth",
    "focus_point",
    "isLive",
    "mode",
)
SCREENSHOT_LOCK = threading.Lock()
ROI1_MARKER_COLOR = (255, 0, 0)
ROI2_MARKER_COLOR = (0, 255, 0)
ROI3_MARKER_COLOR = (255, 255, 0)
ROI4_MARKER_COLOR = (255, 165, 0)
FOCUS_MARKER_COLOR = (128, 0, 128)
DIFFER_MARKER_WIDTH = 3
FOCUS_MARKER_RADIUS = 3
GUIDE_LINE_COLOR = (0, 255, 0)
GUIDE_LINE_WIDTH = 3
GUIDE_LINE_ANGLE_DEGREES = 100.0
FOCUS_Y_OFFSET_MM = 1.0
ROI4_FALLBACK_AFTER_METHODS = {
    "roi1_boundary_after2_fallback_last",
    "stop_fallback",
    "stop_fallback_timeout",
    "final_fallback",
}


class StateInfo(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_int),
        ("AdbServer", ctypes.c_int),
        ("LicenseType", ctypes.c_int),
        ("ControlLinkState", ctypes.c_int),
        ("ImageInfoLinkState", ctypes.c_int),
        ("USBLinkState", ctypes.c_int),
        ("AppRunState", ctypes.c_int),
    ]


@dataclass(frozen=True)
class FrameSnapshot:
    image: np.ndarray
    seq: int
    ts: float


@dataclass(frozen=True)
class DeviceStateSnapshot:
    Version: int
    AdbServer: int
    LicenseType: int
    ControlLinkState: int
    ImageInfoLinkState: int
    USBLinkState: int
    AppRunState: int
    ts: float


@dataclass(frozen=True)
class OfflineConfig:
    screenshot_test_enabled: bool = False
    screenshot_capture_bbox: Optional[Tuple[int, int, int, int]] = None
    peak_detect_enabled: bool = False
    roi2_extension_params: dict = field(default_factory=lambda: {"left": 40, "right": 40, "top": 50, "bottom": 30})
    roi3_extension_params: dict = field(default_factory=lambda: {"left": 30, "right": 30, "top": 50, "bottom": 100})
    roi4_rect: Optional[Tuple[int, int, int, int]] = None
    difference_threshold: float = 0.5
    roi4_after_selector: dict = field(default_factory=lambda: {
        "enabled": False,
        "block_size": 24,
        "gray_diff_threshold": 15.0,
        "candidate_area_ratio_threshold": 3.0,
        "descent_low_frame_number": 2,
    })
    roi3_g1_g2_override: dict = field(default_factory=lambda: {"enabled": True, "g1_threshold": 98.0, "g2_threshold": 20.0, "use_peak_max": True})
    roi3_column_diff_override: dict = field(default_factory=lambda: {"enabled": True, "g1_threshold": 99.0, "threshold": 15.0, "use_peak_max": True})
    offline_peak_enabled: bool = False
    offline_peak_threshold: Optional[float] = None
    offline_peak_after_delay_frames: int = 2
    offline_peak_end_diff_threshold: float = 7.0
    debug_save_enabled: bool = False
    debug_save_dir: str = "D:/software_data/tmp"
    offline_tmp_max_buffer_frames: int = 2500
    stop_wait_timeout_seconds: float = 20.0
    image_output_dir: Optional[str] = None
    db_root_dir: Optional[str] = None
    result_flag_path: Optional[str] = None
    focus_guide_angle_degrees: float = GUIDE_LINE_ANGLE_DEGREES
    focus_guide_line_width: int = GUIDE_LINE_WIDTH
    focus_y_offset_mm: float = FOCUS_Y_OFFSET_MM

    @staticmethod
    def default() -> "OfflineConfig":
        return OfflineConfig()


@dataclass
class OfflineFrameRecord:
    frame: np.ndarray
    seq: int
    ts: float
    frame_index: int
    tag: str
    roi1_gray: float


ROI1_BOUNDARY_MAX_INACTIVE_GAP = 1
ROI1_BOUNDARY_ACTIVE_EXTENSION_OFFSET = 9.0
ROI1_BOUNDARY_RETURN_TO_BASELINE_OFFSET = 5.0
ROI1_BOUNDARY_OFFSET = 2


@dataclass
class OfflineSession:
    point_id: object
    duration_s: float
    is_save: bool
    stop_event: threading.Event
    capture_done_event: threading.Event = field(default_factory=threading.Event)
    finished_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    initial_before_record: Optional[OfflineFrameRecord] = None
    before: Optional[np.ndarray] = None
    before_seq: Optional[int] = None
    before_ts: Optional[float] = None
    before_name: str = ""
    after: Optional[np.ndarray] = None
    after_seq: Optional[int] = None
    after_ts: Optional[float] = None
    after_name: str = ""
    after_method: Optional[str] = None
    focus_anchor: Optional[Tuple[int, int]] = None
    focus_depth_mm: Optional[float] = None
    roi2_rect: Optional[Tuple[int, int, int, int]] = None
    roi3_rect: Optional[Tuple[int, int, int, int]] = None
    roi4_rect: Optional[Tuple[int, int, int, int]] = None
    before_mean: Optional[float] = None
    after_mean: Optional[float] = None
    roi2_diff: Optional[float] = None
    roi3_g1: Optional[float] = None
    roi3_g2: Optional[float] = None
    roi3_column_diff: Optional[float] = None
    roi3_override_applied: bool = False
    roi3_override_method: Optional[str] = None
    roi3_override_frame_index: Optional[int] = None
    roi3_override_tag: Optional[str] = None
    roi4_after_selector_applied: bool = False
    roi4_after_frame_index: Optional[int] = None
    roi4_after_method: Optional[str] = None
    roi4_candidate_area_ratio: Optional[float] = None
    roi4_candidate_area_ratio_threshold: Optional[float] = None
    roi4_selector_reason: Optional[str] = None
    final_roi2_color: str = "red"
    response: dict = field(default_factory=dict)
    frame_buffer: list[OfflineFrameRecord] = field(default_factory=list)
    debug_dir: Optional[str] = None
    meta: dict = field(default_factory=dict)
    finalization_stage: Optional[str] = None
    finalization_stage_started_ns: Optional[int] = None
    finalization_started_ns: Optional[int] = None


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_void_p),
        ("lParam", ctypes.c_void_p),
        ("time", ctypes.c_ulong),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


@dataclass(frozen=True)
class ParsedRequest:
    req_type: str
    param: str
    arg: Optional[str]


def configure_runtime_paths() -> None:
    runtime_dir = resolve_runtime_dir(Path(__file__).resolve().parent)
    os.add_dll_directory(str(runtime_dir))

    env_prefix = Path(sys.executable).resolve().parent.parent
    env_bin = env_prefix / "Library" / "bin"
    if env_bin.exists():
        os.add_dll_directory(str(env_bin))
        path_parts = os.environ.get("PATH", "").split(os.pathsep)
        env_bin_text = str(env_bin)
        if env_bin_text not in path_parts:
            os.environ["PATH"] = env_bin_text + os.pathsep + os.environ.get("PATH", "")
    runtime_text = str(runtime_dir)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)


def runtime_has_required_files(base_dir: Path) -> bool:
    return all((base_dir / name).exists() for name in REQUIRED_RUNTIME_FILES)


def resolve_runtime_dir(
    base_dir: Optional[Path] = None,
    external_runtime_dir: Optional[Path] = None,
    env_runtime_dir: Optional[Path] = None,
) -> Path:
    candidates = []
    if env_runtime_dir is not None:
        candidates.append(Path(env_runtime_dir))
    env_value = os.environ.get("PYWRAPPER_RUNTIME_DIR")
    if env_value:
        candidates.append(Path(env_value))
    if base_dir is not None:
        candidates.append(Path(base_dir))
    if external_runtime_dir is None:
        external_runtime_dir = EXTERNAL_RUNTIME_DIR
    candidates.append(Path(external_runtime_dir))

    for candidate in candidates:
        if candidate.exists() and runtime_has_required_files(candidate):
            return candidate
    if base_dir is not None:
        return Path(base_dir)
    return Path(external_runtime_dir)


def log_process_environment(logger: logging.Logger) -> None:
    base_dir = Path(__file__).resolve().parent
    runtime_dir = resolve_runtime_dir(base_dir)
    exe_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else base_dir
    logger.info("process frozen: %s", bool(getattr(sys, "frozen", False)))
    logger.info("sys.executable: %s", sys.executable)
    logger.info("current working directory: %s", os.getcwd())
    logger.info("module directory: %s", base_dir)
    logger.info("exe directory: %s", exe_dir)
    logger.info("runtime directory: %s", runtime_dir)
    for name in REQUIRED_RUNTIME_FILES:
        path = runtime_dir / name
        logger.info("required file %s exists=%s path=%s", name, path.exists(), path)


def device_state_to_dict(state: Optional[DeviceStateSnapshot]) -> dict:
    if state is None:
        return {"state": None}
    return {
        "Version": state.Version,
        "AdbServer": state.AdbServer,
        "LicenseType": state.LicenseType,
        "ControlLinkState": state.ControlLinkState,
        "ImageInfoLinkState": state.ImageInfoLinkState,
        "USBLinkState": state.USBLinkState,
        "AppRunState": state.AppRunState,
        "ts": state.ts,
    }


def is_device_connected(state: Optional[DeviceStateSnapshot]) -> bool:
    if state is None:
        return False
    return (
        state.USBLinkState == 1
        and state.ControlLinkState == 1
        and state.ImageInfoLinkState == 1
    )


def exit_process_after_failed_online_reconnect(
    logger: Optional[logging.Logger],
    state: Optional[DeviceStateSnapshot],
) -> None:
    state_text = safe_json_text(device_state_to_dict(state))
    if logger is not None:
        logger.critical(
            "online_device_reconnect_failed_exit_process exit_code=%s state=%s",
            DEVICE_RECONNECT_FAILED_EXIT_CODE,
            state_text,
        )
        for handler in logger.handlers:
            handler.flush()
    os._exit(DEVICE_RECONNECT_FAILED_EXIT_CODE)
    raise RuntimeError("os._exit returned unexpectedly after failed ONLINE reconnect")


def log_adb_devices(logger: logging.Logger) -> None:
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        logger.exception("adb devices failed: %s", exc)
        return

    logger.info("adb devices exit_code=%s", result.returncode)
    logger.info("adb devices stdout: %s", result.stdout.strip().replace("\n", " | "))
    stderr = result.stderr.strip()
    if stderr:
        logger.warning("adb devices stderr: %s", stderr.replace("\n", " | "))


def import_mobile_comm():
    configure_runtime_paths()
    import PyMobileComm

    return PyMobileComm


def build_provider_focus_point(focus_x, focus_y) -> Optional[str]:
    if focus_x is None or focus_y is None:
        return None
    return f"PointF({focus_x}, {focus_y})"


def normalize_provider_payload(raw_data: dict) -> dict:
    if raw_data is None:
        raise ValueError("RequestContentProvider callback returned None")
    if not isinstance(raw_data, dict):
        raise TypeError(f"RequestContentProvider callback must decode to dict, got {type(raw_data).__name__}")

    normalized = dict(raw_data)
    if normalized.get("focus_point") in (None, ""):
        focus_point = build_provider_focus_point(normalized.get("focus_x"), normalized.get("focus_y"))
        if focus_point is not None:
            normalized["focus_point"] = focus_point
    return normalized


def parse_provider_callback_payload(raw_payload) -> dict:
    if raw_payload is None:
        raise ValueError("RequestContentProvider callback returned no payload")

    if isinstance(raw_payload, dict):
        return normalize_provider_payload(raw_payload)

    if isinstance(raw_payload, (bytes, bytearray)):
        text = raw_payload.decode("utf-8")
    else:
        text = str(raw_payload)

    if not text.strip():
        raise ValueError("RequestContentProvider callback returned empty payload")

    try:
        decoded = json.loads(text)
    except Exception as primary_exc:
        object_start = text.find("{")
        if object_start < 0:
            raise ValueError("RequestContentProvider callback returned invalid JSON") from primary_exc
        object_end = scan_json_end(text, object_start)
        if object_end < 0:
            raise ValueError("RequestContentProvider callback returned invalid JSON") from primary_exc
        embedded_text = text[object_start:object_end]
        try:
            decoded = json.loads(embedded_text)
        except Exception as exc:
            raise ValueError("RequestContentProvider callback returned invalid JSON") from exc

    return normalize_provider_payload(decoded)


def parse_focus_point(value) -> Optional[Tuple[int, int]]:
    if value is None:
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return int(float(value[0])), int(float(value[1]))
        except Exception:
            return None

    text = str(value).strip()
    match = re.search(r"PointF\(\s*([^,\s]+)\s*,\s*([^)]+?)\s*\)", text)
    if not match:
        return None
    try:
        return int(float(match.group(1))), int(float(match.group(2)))
    except Exception:
        return None


def parse_focus_depth_mm(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        depth_mm = float(value)
    except Exception:
        return None
    if depth_mm <= 0.0:
        return None
    return depth_mm


def validate_focus_y_offset_mm(value) -> float:
    try:
        offset_mm = float(value)
    except Exception as exc:
        raise ValueError(f"focus_guides.y_offset_mm must be a number, got {value}") from exc
    if offset_mm < 0.0:
        raise ValueError(f"focus_guides.y_offset_mm must be >= 0, got {value}")
    return offset_mm


def compute_roi_region(
    frame_size: Tuple[int, int],
    anchor: Tuple[int, int],
    extension_params: dict,
) -> Optional[Tuple[int, int, int, int]]:
    width, height = frame_size
    ax, ay = anchor
    try:
        left = int(extension_params["left"])
        right = int(extension_params["right"])
        top = int(extension_params["top"])
        bottom = int(extension_params["bottom"])
    except Exception:
        return None

    x1 = int(ax) - left
    y1 = int(ay) - top
    x2 = int(ax) + right
    y2 = int(ay) + bottom
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def roi_gray_mean(image: np.ndarray, rect: Tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = rect
    roi = image[y1:y2, x1:x2]
    if roi.size == 0:
        raise ValueError("empty ROI")
    if roi.ndim == 3:
        roi = roi.astype(np.float32)
        gray = 0.299 * roi[:, :, 0] + 0.587 * roi[:, :, 1] + 0.114 * roi[:, :, 2]
        return float(np.mean(gray))
    return float(np.mean(roi.astype(np.float32)))


def crop_rect(image: np.ndarray, rect: Tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = rect
    cropped = image[y1:y2, x1:x2]
    if cropped.size == 0:
        raise ValueError(f"empty crop for rect={rect}")
    return np.array(cropped, copy=True)


def pil_image_from_array(image: np.ndarray) -> Image.Image:
    arr = np.asarray(image)
    if arr.ndim == 2:
        return Image.fromarray(arr)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        return Image.fromarray(arr.astype(np.uint8))
    elif arr.ndim == 3 and arr.shape[2] == 4:
        return Image.fromarray(arr.astype(np.uint8))
    raise ValueError(f"unsupported image shape for png: {arr.shape}")


def write_png(path: Path, image: np.ndarray) -> None:
    pil_image = pil_image_from_array(image)
    path.parent.mkdir(parents=True, exist_ok=True)
    pil_image.save(path, format="PNG")


def gray_image(image: np.ndarray) -> np.ndarray:
    arr = np.asarray(image, dtype=np.float32)
    if arr.ndim == 3:
        return 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    return arr


def frame_gray_mean(image: np.ndarray) -> float:
    gray = gray_image(image)
    if gray.size == 0:
        raise ValueError("empty frame")
    return float(np.mean(gray))


def compute_roi3_metrics(image: np.ndarray, rect: Tuple[int, int, int, int]) -> dict:
    x1, y1, x2, y2 = rect
    roi = np.asarray(image)[y1:y2, x1:x2]
    if roi.size == 0:
        return {"roi3_mean": None, "g1": None, "g2": None, "column_diff": None}
    gray = gray_image(roi)
    total = int(gray.size)
    if total <= 0:
        return {"roi3_mean": None, "g1": None, "g2": None, "column_diff": None}
    clipped = np.clip(gray, 0, 255).astype(np.uint8)
    hist = np.bincount(clipped.ravel(), minlength=256).astype(np.float64)
    g1 = float((np.sum(hist[80:256]) / total) * 100.0)
    g2 = float((np.sum(hist[150:256]) / total) * 100.0)
    col_means = np.mean(gray, axis=0)
    column_diff = float(np.max(col_means) - np.min(col_means)) if col_means.size else 0.0
    return {
        "roi3_mean": float(np.mean(gray)),
        "g1": g1,
        "g2": g2,
        "column_diff": column_diff,
    }


def validate_roi4_rect_for_image(
    rect: Tuple[int, int, int, int],
    image: np.ndarray,
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = [int(v) for v in rect]
    height, width = np.asarray(image).shape[:2]
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid ROI4 rect={rect}")
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        raise ValueError(f"ROI4 rect outside image bounds rect={rect} size={(width, height)}")
    return x1, y1, x2, y2


def compute_roi4_mask_metrics(
    before: np.ndarray,
    after: np.ndarray,
    rect: Tuple[int, int, int, int],
    block_size: int,
    gray_diff_threshold: float,
) -> dict:
    if block_size <= 0:
        raise ValueError(f"ROI4 block_size must be > 0, got {block_size}")
    threshold = float(gray_diff_threshold)
    if threshold <= 0.0:
        raise ValueError(f"ROI4 gray_diff_threshold must be > 0, got {gray_diff_threshold}")
    before_arr = np.asarray(before)
    after_arr = np.asarray(after)
    if before_arr.shape[:2] != after_arr.shape[:2]:
        raise ValueError(f"ROI4 before/after image size mismatch before={before_arr.shape[:2]} after={after_arr.shape[:2]}")
    x1, y1, x2, y2 = validate_roi4_rect_for_image(rect, before_arr)
    validate_roi4_rect_for_image(rect, after_arr)

    before_gray = gray_image(before_arr[y1:y2, x1:x2])
    after_gray = gray_image(after_arr[y1:y2, x1:x2])
    height, width = before_gray.shape[:2]
    roi_area = int(width * height)
    if roi_area <= 0:
        raise ValueError(f"empty ROI4 rect={rect}")

    cols = int(math.ceil(width / float(block_size)))
    rows = int(math.ceil(height / float(block_size)))
    diffs: list[float] = []
    areas: list[int] = []
    mask: list[int] = []

    for gy in range(rows):
        for gx in range(cols):
            bx1 = gx * block_size
            by1 = gy * block_size
            bx2 = min(bx1 + block_size, width)
            by2 = min(by1 + block_size, height)
            area = int((bx2 - bx1) * (by2 - by1))
            before_mean = float(np.mean(before_gray[by1:by2, bx1:bx2]))
            after_mean = float(np.mean(after_gray[by1:by2, bx1:bx2]))
            diff = after_mean - before_mean
            diffs.append(diff)
            areas.append(area)
            mask.append(1 if diff > threshold else 0)

    candidate_area = int(sum(area for area, active in zip(areas, mask) if active))
    candidate_block_count = int(sum(mask))
    largest_indices = find_largest_roi4_component(mask, cols, rows)
    largest_area = int(sum(areas[idx] for idx in largest_indices))
    largest_mean_diff = (
        float(sum(diffs[idx] for idx in largest_indices) / len(largest_indices))
        if largest_indices
        else 0.0
    )

    return {
        "candidate_block_count": candidate_block_count,
        "candidate_area_ratio": float(candidate_area / roi_area * 100.0),
        "largest_area_ratio": float(largest_area / roi_area * 100.0),
        "largest_mean_diff": largest_mean_diff,
        "max_diff": float(max(diffs)) if diffs else 0.0,
        "min_diff": float(min(diffs)) if diffs else 0.0,
        "cols": cols,
        "rows": rows,
    }


def find_largest_roi4_component(mask: list[int], cols: int, rows: int) -> set[int]:
    visited = [False] * len(mask)
    largest: set[int] = set()
    directions = ((1, 0), (-1, 0), (0, 1), (0, -1))
    for index, active in enumerate(mask):
        if active != 1 or visited[index]:
            continue
        current_set: set[int] = set()
        queue = [index]
        visited[index] = True
        head = 0
        while head < len(queue):
            current = queue[head]
            head += 1
            current_set.add(current)
            cx = current % cols
            cy = current // cols
            for dx, dy in directions:
                nx = cx + dx
                ny = cy + dy
                if nx < 0 or nx >= cols or ny < 0 or ny >= rows:
                    continue
                ni = ny * cols + nx
                if mask[ni] == 1 and not visited[ni]:
                    visited[ni] = True
                    queue.append(ni)
        if len(current_set) > len(largest):
            largest = current_set
    return largest


def positive_diff_image(before: np.ndarray, after: np.ndarray) -> np.ndarray:
    before_arr = np.asarray(before, dtype=np.float32)
    after_arr = np.asarray(after, dtype=np.float32)
    if before_arr.ndim == 3 and before_arr.shape[2] == 4:
        before_arr = before_arr[:, :, :3]
    if after_arr.ndim == 3 and after_arr.shape[2] == 4:
        after_arr = after_arr[:, :, :3]
    diff = after_arr - before_arr
    diff[diff < 0] = 0
    return diff.astype(np.uint8)


def draw_marker_rect(
    draw: ImageDraw.ImageDraw,
    image_size: Tuple[int, int],
    rect: Tuple[int, int, int, int],
    color: Tuple[int, int, int],
) -> None:
    width, height = image_size
    if width <= 0 or height <= 0:
        raise ValueError(f"cannot draw marker on empty image size={image_size}")
    x1, y1, x2, y2 = [int(v) for v in rect]
    if x2 <= x1 or y2 <= y1:
        raise ValueError(f"invalid marker rect={rect}")
    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        raise ValueError(f"marker rect outside image bounds rect={rect} size={image_size}")
    left = x1
    top = y1
    right = x2 - 1
    bottom = y2 - 1
    draw.rectangle((left, top, right, bottom), outline=color, width=DIFFER_MARKER_WIDTH)


def draw_focus_marker(
    draw: ImageDraw.ImageDraw,
    image_size: Tuple[int, int],
    focus_anchor: Tuple[int, int],
) -> None:
    x, y = validate_focus_anchor(image_size, focus_anchor)
    radius = FOCUS_MARKER_RADIUS
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=FOCUS_MARKER_COLOR)


def validate_focus_anchor(image_size: Tuple[int, int], focus_anchor: Tuple[int, int]) -> Tuple[int, int]:
    width, height = image_size
    x, y = [int(v) for v in focus_anchor]
    if x < 0 or y < 0 or x >= width or y >= height:
        raise ValueError(f"focus marker outside image bounds focus={focus_anchor} size={image_size}")
    return x, y


def resolve_focus_overlay_anchor(
    image_size: Tuple[int, int],
    session: "OfflineSession",
    config: OfflineConfig,
) -> Optional[Tuple[int, int]]:
    if session.focus_anchor is None:
        return None
    x, y = validate_focus_anchor(image_size, session.focus_anchor)
    offset_mm = validate_focus_y_offset_mm(config.focus_y_offset_mm)
    if offset_mm == 0.0:
        return x, y
    depth_mm = session.focus_depth_mm
    if depth_mm is None or depth_mm <= 0.0:
        raise ValueError("provider depth is required and must be > 0 when focus_guides.y_offset_mm > 0")
    width, height = image_size
    offset_px = int(round(offset_mm * float(height) / float(depth_mm)))
    overlay_anchor = (x, y + offset_px)
    try:
        return validate_focus_anchor(image_size, overlay_anchor)
    except ValueError as exc:
        raise ValueError(
            "focus overlay outside image bounds "
            f"focus={session.focus_anchor} offset_mm={offset_mm} depth_mm={depth_mm} "
            f"offset_px={offset_px} size={(width, height)}"
        ) from exc


def clip_focus_guide_endpoint(
    image_size: Tuple[int, int],
    focus_anchor: Tuple[int, int],
    direction: Tuple[float, float],
) -> Tuple[int, int]:
    width, height = image_size
    x, y = validate_focus_anchor(image_size, focus_anchor)
    dx, dy = direction
    candidates = []
    if dx < 0:
        candidates.append((0 - x) / dx)
    elif dx > 0:
        candidates.append(((width - 1) - x) / dx)
    if dy < 0:
        candidates.append((0 - y) / dy)
    elif dy > 0:
        candidates.append(((height - 1) - y) / dy)
    positive_candidates = [t for t in candidates if t >= 0]
    if not positive_candidates:
        raise ValueError(f"focus guide has no image-boundary endpoint focus={focus_anchor} direction={direction} size={image_size}")
    distance = min(positive_candidates)
    end_x = int(round(x + dx * distance))
    end_y = int(round(y + dy * distance))
    return max(0, min(width - 1, end_x)), max(0, min(height - 1, end_y))


def draw_focus_guide_lines(
    draw: ImageDraw.ImageDraw,
    image_size: Tuple[int, int],
    focus_anchor: Tuple[int, int],
    angle_degrees: float,
    line_width: int,
) -> None:
    x, y = validate_focus_anchor(image_size, focus_anchor)
    guide_angle, guide_width = validate_focus_guide_geometry(angle_degrees, line_width)
    half_angle = math.radians(guide_angle / 2.0)
    directions = (
        (-math.sin(half_angle), -math.cos(half_angle)),
        (math.sin(half_angle), -math.cos(half_angle)),
    )
    for direction in directions:
        end_x, end_y = clip_focus_guide_endpoint(image_size, (x, y), direction)
        draw.line((x, y, end_x, end_y), fill=GUIDE_LINE_COLOR, width=guide_width)


def validate_focus_guide_geometry(angle_degrees, line_width) -> Tuple[float, int]:
    guide_angle = float(angle_degrees)
    guide_width = int(line_width)
    if guide_angle <= 0.0 or guide_angle >= 180.0:
        raise ValueError(f"focus guide angle_degrees must be > 0 and < 180, got {angle_degrees}")
    if guide_width <= 0:
        raise ValueError(f"focus guide line_width must be > 0, got {line_width}")
    return guide_angle, guide_width


def render_frame_with_focus_guides(frame: np.ndarray, session: "OfflineSession", config: OfflineConfig) -> np.ndarray:
    if session.focus_anchor is None:
        return frame
    image = pil_image_from_array(frame)
    if image.mode == "L":
        image = image.convert("RGB")
    draw = ImageDraw.Draw(image)
    overlay_anchor = resolve_focus_overlay_anchor(image.size, session, config)
    if overlay_anchor is None:
        return np.array(image)
    draw_focus_guide_lines(
        draw,
        image.size,
        overlay_anchor,
        config.focus_guide_angle_degrees,
        config.focus_guide_line_width,
    )
    draw_focus_marker(draw, image.size, overlay_anchor)
    return np.array(image)


def draw_differ_roi_markers(
    draw: ImageDraw.ImageDraw,
    image_size: Tuple[int, int],
    session: "OfflineSession",
    focus_marker_anchor: Optional[Tuple[int, int]] = None,
) -> None:
    width, height = image_size
    draw_marker_rect(draw, image_size, (0, 0, width, height), ROI1_MARKER_COLOR)
    if session.roi2_rect is not None:
        draw_marker_rect(draw, image_size, session.roi2_rect, ROI2_MARKER_COLOR)
    if session.roi3_rect is not None:
        draw_marker_rect(draw, image_size, session.roi3_rect, ROI3_MARKER_COLOR)
    if session.roi4_rect is not None:
        draw_marker_rect(draw, image_size, session.roi4_rect, ROI4_MARKER_COLOR)
    if focus_marker_anchor is not None:
        draw_focus_marker(draw, image_size, focus_marker_anchor)


def format_frame_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d_%H-%M-%S.%f")[:-3]


def write_result_flag(path_text: Optional[str], ok: bool) -> None:
    if not path_text:
        return
    out_path = Path(path_text)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text("1" if ok else "0", encoding="utf-8")
    os.replace(tmp_path, out_path)


def update_segment_images_info(db_root_dir: Optional[str], point_id, before_path: str, after_path: str, treatment_ok: bool) -> None:
    if not db_root_dir:
        return
    db_root = Path(db_root_dir)
    db_paths = [db_root / "ccwssm", db_root / "zccwssm"]
    modify_time = datetime.now().strftime("%Y_%m_%d-%H_%M_%S_%f")[:-3]
    image_path = before_path + ";" + after_path + ";" + after_path.replace("_after", "_diff")
    treat_flag = 1 if treatment_ok else 0
    sql = """
        UPDATE SegmentImagesInfo
        SET ImagePath = ?, TreatFlag = ?, ModifyTime = ?
        WHERE ID = ?
    """
    for db_path in db_paths:
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        try:
            cur = conn.cursor()
            cur.execute(sql, (image_path, treat_flag, modify_time, point_id))
            if cur.rowcount <= 0:
                raise LookupError(f"SegmentImagesInfo update matched no rows in {db_path} for point_id={point_id}")
            conn.commit()
            cur.close()
        finally:
            conn.close()


def format_buffered_frame_name(frame_index: int, ts: float, tag: str) -> str:
    return f"{int(frame_index):05d}_{format_frame_timestamp(ts)}_{tag}.png".replace(":", "-")


def write_jsonl_line(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_diff_overlay_judgement_lines(session: "OfflineSession", config: OfflineConfig):
    thr = float(config.difference_threshold) if config.difference_threshold is not None else None
    roi2_ok = bool(session.roi2_diff is not None and thr is not None and float(session.roi2_diff) >= float(thr))
    first_line = (
        "1. ROI2: current=N/A / threshold=N/A"
        if session.roi2_diff is None or thr is None
        else f"1. ROI2: current={float(session.roi2_diff):.3f} / threshold={float(thr):.3f}"
    )
    lines = [
        first_line,
        "2. ROI2: diff/threshold=N/A"
        if session.roi2_diff is None or thr is None
        else f"2. ROI2: d={float(session.roi2_diff):.3f} / thr={float(thr):.3f}",
        "3. ROI3(G1/G2): N/A"
        if session.roi3_g1 is None or session.roi3_g2 is None
        else f"3. ROI3: G1={float(session.roi3_g1):.2f} G2={float(session.roi3_g2):.2f}",
        "4. ROI3(colDiff): N/A"
        if session.roi3_column_diff is None
        else f"4. ROI3: colDiff={float(session.roi3_column_diff):.2f}",
        "5. ROI4: N/A"
        if session.roi4_candidate_area_ratio is None or session.roi4_candidate_area_ratio_threshold is None
        else (
            f"5. ROI4: cand={float(session.roi4_candidate_area_ratio):.2f}% / "
            f"thr={float(session.roi4_candidate_area_ratio_threshold):.2f}% frame={session.roi4_after_frame_index}"
        ),
    ]
    line_ok = [
        roi2_ok,
        roi2_ok,
        bool(session.roi3_override_method == "roi3_g1_g2"),
        bool(session.roi3_override_method == "roi3_column_diff"),
        bool(session.roi4_after_selector_applied),
    ]
    return lines, line_ok


def build_roi4_diagnostics(session: "OfflineSession") -> dict:
    return {
        "roi4_rect": [int(v) for v in session.roi4_rect] if session.roi4_rect is not None else None,
        "roi4_after_selector_applied": bool(session.roi4_after_selector_applied),
        "roi4_after_frame_index": int(session.roi4_after_frame_index) if session.roi4_after_frame_index is not None else None,
        "roi4_after_method": session.roi4_after_method,
        "roi4_candidate_area_ratio": round(float(session.roi4_candidate_area_ratio), 6) if session.roi4_candidate_area_ratio is not None else None,
        "roi4_candidate_area_ratio_threshold": round(float(session.roi4_candidate_area_ratio_threshold), 6) if session.roi4_candidate_area_ratio_threshold is not None else None,
        "roi4_selector_reason": session.roi4_selector_reason,
    }


def render_diff_with_overlay(session: "OfflineSession", config: OfflineConfig) -> Optional[np.ndarray]:
    if session.before is None or session.after is None:
        return None
    diff = positive_diff_image(session.before, session.after)
    rgb = np.asarray(diff, dtype=np.uint8)
    if rgb.ndim == 2:
        rgb = np.stack([rgb, rgb, rgb], axis=2)
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
    focus_overlay_anchor = resolve_focus_overlay_anchor(image.size, session, config)
    if session.focus_anchor is not None:
        draw_focus_guide_lines(
            draw,
            image.size,
            focus_overlay_anchor,
            config.focus_guide_angle_degrees,
            config.focus_guide_line_width,
        )
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\msyh.ttc", 18)
    except Exception:
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None

    lines, line_ok = build_diff_overlay_judgement_lines(session, config)
    y = 20
    for idx, line in enumerate(lines):
        fill = (0, 200, 0) if line_ok[idx] else (255, 0, 0)
        draw.text((20, y), line, fill=fill, font=font)
        y += 20
    draw_differ_roi_markers(draw, image.size, session, focus_overlay_anchor)
    return np.array(image)


class DebugFrameSaver:
    def create_session_dir(self, root_dir: str, point_id) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        day = datetime.now().strftime("%Y%m%d")
        safe_point = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(point_id))
        path = Path(root_dir) / "pywrapper_offline" / day / f"{safe_point}_{ts}"
        path.mkdir(parents=True, exist_ok=False)
        return str(path)

    def save_stage(
        self,
        debug_dir: str,
        stage: str,
        frame: np.ndarray,
        roi2_rect: Tuple[int, int, int, int],
        roi3_rect: Tuple[int, int, int, int],
    ) -> None:
        base = Path(debug_dir)
        write_png(base / f"{stage}_roi1.png", frame)
        write_png(base / f"{stage}_roi2.png", crop_rect(frame, roi2_rect))
        write_png(base / f"{stage}_roi3.png", crop_rect(frame, roi3_rect))

    def write_meta(self, debug_dir: str, meta: dict) -> None:
        path = Path(debug_dir) / "meta.json"
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


class ScreenCaptureFrameSource:
    def __init__(
        self,
        bbox: Optional[Tuple[int, int, int, int]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._bbox = bbox
        self._logger = logger
        self._lock = threading.Lock()
        self._seq = 0
        if self._logger is not None:
            self._logger.info("screenshot frame source enabled bbox=%s", self._bbox)

    def __call__(self) -> FrameSnapshot:
        with SCREENSHOT_LOCK:
            image = ImageGrab.grab(bbox=self._bbox) if self._bbox is not None else ImageGrab.grab()
        frame = np.array(image.convert("RGB"), copy=True)
        with self._lock:
            self._seq += 1
            seq = self._seq
        return FrameSnapshot(frame, seq, time.time())


def resolve_settings_path() -> Path:
    if getattr(sys, "frozen", False):
        candidates = [
            Path(sys.executable).resolve().parent / "settings",
            Path(__file__).resolve().parent / "settings",
        ]
    else:
        candidates = [Path(__file__).resolve().parents[2] / "settings"]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def load_offline_config(logger: logging.Logger) -> OfflineConfig:
    settings_path = resolve_settings_path()
    if not settings_path.exists():
        raise FileNotFoundError(f"required settings file not found: {settings_path}")

    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    return parse_offline_config(settings, logger)


def parse_roi4_rect(peak: dict, selector_enabled: bool) -> Optional[Tuple[int, int, int, int]]:
    raw = peak.get("roi4_rect")
    if raw is None:
        if selector_enabled:
            raise ValueError("settings.peak_detect.roi4_rect is required when roi4_after_selector.enabled=true")
        return None
    if not isinstance(raw, dict):
        raise ValueError("settings.peak_detect.roi4_rect must be an object")
    for key in ("x", "y", "width", "height"):
        if key not in raw:
            raise ValueError(f"settings.peak_detect.roi4_rect.{key} is required")
    x = int(raw["x"])
    y = int(raw["y"])
    width = int(raw["width"])
    height = int(raw["height"])
    if width <= 0 or height <= 0:
        raise ValueError("settings.peak_detect.roi4_rect width and height must be > 0")
    if x < 0 or y < 0:
        raise ValueError("settings.peak_detect.roi4_rect x and y must be >= 0")
    return x, y, x + width, y + height


def parse_roi4_after_selector(peak: dict) -> dict:
    raw = peak.get("roi4_after_selector")
    defaults = {
        "enabled": False,
        "block_size": 24,
        "gray_diff_threshold": 15.0,
        "candidate_area_ratio_threshold": 3.0,
        "descent_low_frame_number": 2,
    }
    if raw is None:
        return defaults
    if not isinstance(raw, dict):
        raise ValueError("settings.peak_detect.roi4_after_selector must be an object")
    result = dict(defaults)
    result.update(raw)
    result["enabled"] = bool(result.get("enabled", False))
    result["block_size"] = int(result["block_size"])
    result["gray_diff_threshold"] = float(result["gray_diff_threshold"])
    result["candidate_area_ratio_threshold"] = float(result["candidate_area_ratio_threshold"])
    result["descent_low_frame_number"] = int(result["descent_low_frame_number"])
    if result["block_size"] <= 0:
        raise ValueError("settings.peak_detect.roi4_after_selector.block_size must be > 0")
    if result["gray_diff_threshold"] <= 0.0:
        raise ValueError("settings.peak_detect.roi4_after_selector.gray_diff_threshold must be > 0")
    if result["candidate_area_ratio_threshold"] <= 0.0:
        raise ValueError("settings.peak_detect.roi4_after_selector.candidate_area_ratio_threshold must be > 0")
    if result["descent_low_frame_number"] <= 0:
        raise ValueError("settings.peak_detect.roi4_after_selector.descent_low_frame_number must be > 0")
    return result


def parse_offline_config(settings: dict, logger: logging.Logger) -> OfflineConfig:
    screenshot_cfg = settings.get("offline_screenshot_test")
    if not isinstance(screenshot_cfg, dict):
        screenshot_cfg = {}
    peak_select = settings.get("offline_peak")
    if not isinstance(peak_select, dict):
        peak_select = {}
    peak = settings.get("peak_detect")
    if not isinstance(peak, dict):
        raise ValueError("settings.peak_detect is required for OFFLINE")
    roi2_ext = peak.get("roi2_extension_params")
    if not isinstance(roi2_ext, dict):
        raise ValueError("settings.peak_detect.roi2_extension_params is required for OFFLINE")
    roi3_ext = peak.get("roi3_extension_params")
    if not isinstance(roi3_ext, dict):
        raise ValueError("settings.peak_detect.roi3_extension_params is required for OFFLINE")
    roi4_after_selector = parse_roi4_after_selector(peak)
    roi4_rect = parse_roi4_rect(peak, bool(roi4_after_selector.get("enabled", False)))
    threshold = peak.get("difference_threshold")
    if threshold is None:
        raise ValueError("settings.peak_detect.difference_threshold is required for OFFLINE")
    if bool(peak_select.get("enabled", False)) and peak_select.get("threshold") is None:
        raise ValueError("settings.offline_peak.threshold is required when offline_peak.enabled=true")
    tmp = settings.get("offline_tmp_frames")
    if not isinstance(tmp, dict):
        raise ValueError("settings.offline_tmp_frames is required for OFFLINE debug saving")
    debug_save_dir = tmp.get("dir")
    if not debug_save_dir:
        raise ValueError("settings.offline_tmp_frames.dir is required for OFFLINE debug saving")
    screenshot_capture_bbox = None
    capture_cfg = settings.get("roi1_capture") or settings.get("capture_roi") or {}
    if isinstance(capture_cfg, dict) and bool(capture_cfg.get("enabled", False)):
        x1 = int(capture_cfg.get("x1", 0))
        y1 = int(capture_cfg.get("y1", 0))
        x2 = int(capture_cfg.get("x2", 0))
        y2 = int(capture_cfg.get("y2", 0))
        if x2 > x1 and y2 > y1:
            screenshot_capture_bbox = (x1, y1, x2, y2)
    stop_wait_timeout_seconds = settings.get("offline_stop_wait_timeout_seconds", 20.0)
    g1g2_override = peak.get("roi3_g1_g2_override") or peak.get("g1_g2_override") or {}
    column_override = peak.get("roi3_column_diff_override") or {}
    focus_guides = settings.get("focus_guides")
    if focus_guides is None:
        focus_guides = {}
    if not isinstance(focus_guides, dict):
        raise ValueError("settings.focus_guides must be an object when provided")
    focus_guide_angle_degrees, focus_guide_line_width = validate_focus_guide_geometry(
        focus_guides.get("angle_degrees", GUIDE_LINE_ANGLE_DEGREES),
        focus_guides.get("line_width", GUIDE_LINE_WIDTH),
    )
    focus_y_offset_mm = validate_focus_y_offset_mm(focus_guides.get("y_offset_mm", FOCUS_Y_OFFSET_MM))
    image_output_dir = settings.get("image_output_dir", "D:/software_data/imgs")
    db_root_dir = settings.get("db_root_dir", "D:/software_data")
    result_flag_path = settings.get("result_flag_path", "D:/software_data/result.txt")

    config = OfflineConfig(
        screenshot_test_enabled=bool(screenshot_cfg.get("enabled", False)),
        screenshot_capture_bbox=screenshot_capture_bbox,
        peak_detect_enabled=True,
        roi2_extension_params=dict(roi2_ext),
        roi3_extension_params=dict(roi3_ext),
        roi4_rect=roi4_rect,
        difference_threshold=float(threshold),
        roi4_after_selector=roi4_after_selector,
        roi3_g1_g2_override=dict(g1g2_override) if isinstance(g1g2_override, dict) else {"enabled": True, "g1_threshold": 98.0, "g2_threshold": 20.0, "use_peak_max": True},
        roi3_column_diff_override=dict(column_override) if isinstance(column_override, dict) else {"enabled": True, "g1_threshold": 99.0, "threshold": 15.0, "use_peak_max": True},
        offline_peak_enabled=bool(peak_select.get("enabled", False)),
        offline_peak_threshold=float(peak_select.get("threshold")) if peak_select.get("threshold") is not None else None,
        offline_peak_after_delay_frames=int(peak_select.get("after_delay_frames", 2)),
        offline_peak_end_diff_threshold=float(peak_select.get("end_diff_threshold", 7.0)),
        debug_save_enabled=bool(tmp.get("enabled", False)),
        debug_save_dir=str(debug_save_dir),
        offline_tmp_max_buffer_frames=int(tmp.get("max_buffer_frames", 2500)),
        stop_wait_timeout_seconds=float(stop_wait_timeout_seconds),
        image_output_dir=str(image_output_dir) if image_output_dir else None,
        db_root_dir=str(db_root_dir) if db_root_dir else None,
        result_flag_path=str(result_flag_path) if result_flag_path else None,
        focus_guide_angle_degrees=focus_guide_angle_degrees,
        focus_guide_line_width=focus_guide_line_width,
        focus_y_offset_mm=focus_y_offset_mm,
    )
    logger.info(
        "offline config loaded: screenshot_test_enabled=%s screenshot_capture_bbox=%s peak_detect_enabled=%s offline_peak_enabled=%s offline_peak_threshold=%s "
        "roi2_extension_params=%s roi3_extension_params=%s roi4_rect=%s difference_threshold=%s roi4_after_selector=%s debug_save_enabled=%s "
        "debug_save_dir=%s stop_wait_timeout_seconds=%s image_output_dir=%s db_root_dir=%s result_flag_path=%s "
        "focus_guide_angle_degrees=%s focus_guide_line_width=%s focus_y_offset_mm=%s",
        config.screenshot_test_enabled,
        config.screenshot_capture_bbox,
        config.peak_detect_enabled,
        config.offline_peak_enabled,
        config.offline_peak_threshold,
        config.roi2_extension_params,
        config.roi3_extension_params,
        config.roi4_rect,
        config.difference_threshold,
        config.roi4_after_selector,
        config.debug_save_enabled,
        config.debug_save_dir,
        config.stop_wait_timeout_seconds,
        config.image_output_dir,
        config.db_root_dir,
        config.result_flag_path,
        config.focus_guide_angle_degrees,
        config.focus_guide_line_width,
        config.focus_y_offset_mm,
    )
    return config


def create_hidden_window() -> int:
    user32 = ctypes.windll.user32
    hwnd = user32.CreateWindowExW(
        0,
        "STATIC",
        "pywrapper_api_server_hidden_d3d",
        0,
        0,
        0,
        1,
        1,
        0,
        0,
        0,
        None,
    )
    if not hwnd:
        raise ctypes.WinError()
    return int(hwnd)


def destroy_window(hwnd: int) -> None:
    if not ctypes.windll.user32.DestroyWindow(hwnd):
        raise ctypes.WinError()


def pump_windows_messages() -> None:
    user32 = ctypes.windll.user32
    msg = MSG()
    while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


class MobileCommEngine:
    def __init__(
        self,
        comm,
        logger: logging.Logger,
        hwnd_factory: Callable[[], int] = create_hidden_window,
        hwnd_destroyer: Callable[[int], None] = destroy_window,
        stream_interval_s: float = 0.016,
    ):
        self._comm = comm
        self._logger = logger
        self._hwnd_factory = hwnd_factory
        self._hwnd_destroyer = hwnd_destroyer
        self._stream_interval_s = stream_interval_s
        self._hwnd: Optional[int] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._frame_lock = threading.Lock()
        self._latest_frame: Optional[FrameSnapshot] = None
        self._frame_seq = 0
        self._state_lock = threading.Lock()
        self._latest_state: Optional[DeviceStateSnapshot] = None

    def configure(self) -> None:
        self._logger.info("registering SetOnImageInfoOnceMsg callback")
        self._comm.SetOnImageInfoOnceMsg(self._on_image_info_received)
        self._logger.info("registering SetOnClientStateInfoOnceMsg callback")
        self._comm.SetOnClientStateInfoOnceMsg(self._on_state_info_received)

        self._hwnd = self._hwnd_factory()
        self._logger.info("created hidden D3D HWND=%s", self._hwnd)
        self._comm.SetD3DRenderHWND(self._hwnd)
        self._logger.info("SetD3DRenderHWND completed")

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="MobileCommStreamRender", daemon=True)
        self._thread.start()
        self._logger.info("StreamRender loop started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            self._logger.info("StreamRender loop stopped")
        if self._hwnd is not None:
            hwnd = self._hwnd
            self._hwnd = None
            self._hwnd_destroyer(hwnd)
            self._logger.info("destroyed hidden D3D HWND=%s", hwnd)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                pump_windows_messages()
                self._comm.StreamRender()
            except Exception:
                self._logger.exception("StreamRender loop failed")
                raise
            self._stop_event.wait(self._stream_interval_s)

    def _on_image_info_received(self, header_ptr, image_matrix) -> None:
        try:
            frame = np.array(image_matrix, copy=True)
        except Exception:
            self._logger.exception("failed to copy image_matrix from image callback")
            return
        with self._frame_lock:
            self._frame_seq += 1
            self._latest_frame = FrameSnapshot(frame, self._frame_seq, time.time())

    def get_latest_frame(self) -> Optional[FrameSnapshot]:
        with self._frame_lock:
            if self._latest_frame is None:
                return None
            return FrameSnapshot(np.array(self._latest_frame.image, copy=True), self._latest_frame.seq, self._latest_frame.ts)

    def get_latest_state(self) -> Optional[DeviceStateSnapshot]:
        with self._state_lock:
            return self._latest_state

    def _on_state_info_received(self, error_info_ptr) -> None:
        if error_info_ptr == 0:
            self._logger.warning("state callback received null pointer")
            return
        try:
            state = ctypes.cast(error_info_ptr, ctypes.POINTER(StateInfo)).contents
        except Exception:
            self._logger.exception("failed to parse state callback pointer")
            return
        snapshot = DeviceStateSnapshot(
            Version=state.Version,
            AdbServer=state.AdbServer,
            LicenseType=state.LicenseType,
            ControlLinkState=state.ControlLinkState,
            ImageInfoLinkState=state.ImageInfoLinkState,
            USBLinkState=state.USBLinkState,
            AppRunState=state.AppRunState,
            ts=time.time(),
        )
        with self._state_lock:
            self._latest_state = snapshot


class PyMobileCommProvider:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self._logger = logger or logging.getLogger("pywrapper_api_server")
        self._logger.info("initializing PyMobileComm provider")
        module = import_mobile_comm()
        self._logger.info("PyMobileComm module imported from: %s", getattr(module, "__file__", "<unknown>"))
        self._comm = module.CMobileCommunication()
        self._lock = threading.Lock()
        self._request_state_lock = threading.Lock()
        self._pending_provider_event: Optional[threading.Event] = None
        self._pending_provider_payload: Optional[dict] = None
        self._pending_provider_error: Optional[Exception] = None
        self._logger.info("registering SetOnControlOnceMsg callback")
        self._comm.SetOnControlOnceMsg(self._on_control_received)
        self._engine = MobileCommEngine(self._comm, self._logger)
        self._engine.configure()
        log_adb_devices(self._logger)
        self._logger.info("calling RestartAdbServer")
        self._comm.RestartAdbServer()
        log_adb_devices(self._logger)
        self._logger.info("calling Auto_Initialize")
        self._comm.Auto_Initialize()
        self._engine.start()
        self._logger.info("PyMobileComm provider initialized")

    def _set_pending_provider_result(
        self,
        payload: Optional[dict] = None,
        error: Optional[Exception] = None,
    ) -> None:
        with self._request_state_lock:
            pending_event = self._pending_provider_event
            if pending_event is None:
                self._logger.warning("provider callback received without a pending request")
                return
            self._pending_provider_payload = payload
            self._pending_provider_error = error
        pending_event.set()

    def _on_control_received(self, raw_payload) -> None:
        self._logger.info(
            "RequestContentProvider callback raw payload: type=%s len=%s preview=%r",
            type(raw_payload).__name__,
            len(raw_payload) if isinstance(raw_payload, (str, bytes, bytearray)) else None,
            raw_payload[:500] if isinstance(raw_payload, (str, bytes, bytearray)) else raw_payload,
        )
        try:
            payload = parse_provider_callback_payload(raw_payload)
        except Exception as exc:
            self._logger.exception("failed to parse RequestContentProvider callback payload")
            self._set_pending_provider_result(error=exc)
            return

        self._logger.info(
            "RequestContentProvider callback received keys=%s",
            ",".join(sorted(payload.keys())),
        )
        self._logger.info("RequestContentProvider callback normalized payload: %s", safe_json_text(payload))
        self._set_pending_provider_result(payload=payload)

    def _request_provider_locked(self, timeout_s: float = ONLINE_PROVIDER_TIMEOUT_SECONDS) -> dict:
        wait_timeout_s = max(float(timeout_s), 0.0)
        request_event = threading.Event()
        with self._request_state_lock:
            self._pending_provider_event = request_event
            self._pending_provider_payload = None
            self._pending_provider_error = None

        try:
            self._logger.info("calling RequestContentProvider")
            self._comm.RequestContentProvider()
            if not request_event.wait(timeout=wait_timeout_s):
                raise TimeoutError(f"RequestContentProvider timed out after {wait_timeout_s:.3f}s")

            with self._request_state_lock:
                error = self._pending_provider_error
                data = self._pending_provider_payload

            if error is not None:
                raise error
            if data is None:
                raise ValueError("RequestContentProvider callback returned no payload")

            self._logger.info("RequestContentProvider returned type=%s", type(data).__name__)
            self._logger.info("RequestContentProvider returned data: %s", safe_json_text(data))
            return data
        finally:
            with self._request_state_lock:
                self._pending_provider_event = None
                self._pending_provider_payload = None
                self._pending_provider_error = None

    def fetch(self, timeout_s: float = ONLINE_PROVIDER_TIMEOUT_SECONDS) -> dict:
        with self._lock:
            return self._request_provider_locked(timeout_s=timeout_s)

    def ensure_connected_for_online(
        self,
        timeout_s: float = ONLINE_RECONNECT_TIMEOUT_SECONDS,
        poll_interval_s: float = 0.05,
        trace_id: Optional[str] = None,
    ) -> bool:
        log_online_timepoint(self._logger, trace_id, "device_connect_check_start")
        state = self._engine.get_latest_state()
        connected = is_device_connected(state)
        log_online_timepoint(
            self._logger,
            trace_id,
            "device_connect_check_completed",
            connected=connected,
            state=safe_json_text(device_state_to_dict(state)),
        )
        if connected:
            return True

        self._logger.warning(
            "ONLINE device not connected before provider fetch: %s",
            safe_json_text(device_state_to_dict(state)),
        )
        log_online_timepoint(self._logger, trace_id, "device_reconnect_start")
        self._logger.info("ONLINE reconnect calling RestartAdbServer")
        self._comm.RestartAdbServer()
        self._logger.info("ONLINE reconnect calling Auto_Initialize")
        init_result = self._comm.Auto_Initialize()
        log_online_timepoint(
            self._logger,
            trace_id,
            "device_reconnect_auto_initialize_completed",
            result=init_result,
        )

        deadline = time.monotonic() + max(timeout_s, 0.0)
        final_state = self._engine.get_latest_state()
        while True:
            if is_device_connected(final_state):
                self._logger.info("online_reconnect_success state=%s", safe_json_text(device_state_to_dict(final_state)))
                log_online_timepoint(
                    self._logger,
                    trace_id,
                    "device_reconnect_wait_completed",
                    connected=True,
                    state=safe_json_text(device_state_to_dict(final_state)),
                )
                return True
            if time.monotonic() >= deadline:
                break
            sleep_s = min(max(poll_interval_s, 0.0), max(deadline - time.monotonic(), 0.0))
            if sleep_s > 0:
                time.sleep(sleep_s)
            final_state = self._engine.get_latest_state()

        self._logger.warning(
            "online_device_not_connected_after_reconnect state=%s",
            safe_json_text(device_state_to_dict(final_state)),
        )
        log_online_timepoint(
            self._logger,
            trace_id,
            "device_reconnect_wait_completed",
            connected=False,
            state=safe_json_text(device_state_to_dict(final_state)),
        )
        exit_process_after_failed_online_reconnect(self._logger, final_state)

    def fetch_online(
        self,
        timeout_s: float = ONLINE_PROVIDER_TIMEOUT_SECONDS,
        poll_interval_s: float = 0.05,
        trace_id: Optional[str] = None,
        reconnect_timeout_s: float = ONLINE_RECONNECT_TIMEOUT_SECONDS,
    ) -> dict:
        with self._lock:
            if not self.ensure_connected_for_online(reconnect_timeout_s, poll_interval_s, trace_id=trace_id):
                return {}
            log_online_timepoint(self._logger, trace_id, "provider_fetch_start")
            data = self._request_provider_locked(timeout_s=timeout_s)
            log_online_timepoint(self._logger, trace_id, "provider_fetch_completed", provider_type=type(data).__name__)
            return data

    def get_latest_frame(self) -> Optional[FrameSnapshot]:
        return self._engine.get_latest_frame()

    def close(self) -> None:
        with self._lock:
            self._engine.stop()
            self._logger.info("calling Stop_AutoInitialize")
            self._comm.Stop_AutoInitialize()


class OfflineSessionManager:
    def __init__(
        self,
        provider_fetcher: Callable[[], dict],
        frame_fetcher: Callable[[], Optional[FrameSnapshot]],
        config: OfflineConfig,
        logger: Optional[logging.Logger] = None,
        debug_saver: Optional[DebugFrameSaver] = None,
        screenshot_frame_fetcher: Optional[Callable[[], Optional[FrameSnapshot]]] = None,
    ):
        self._provider_fetcher = provider_fetcher
        self._config = config
        self._logger = logger or logging.getLogger("pywrapper_api_server")
        self._debug_saver = debug_saver or DebugFrameSaver()
        self._capture_source = "screenshot" if bool(config.screenshot_test_enabled) else "image_matrix"
        if bool(config.screenshot_test_enabled):
            self._frame_fetcher = screenshot_frame_fetcher or ScreenCaptureFrameSource(
                bbox=config.screenshot_capture_bbox,
                logger=self._logger,
            )
        else:
            self._frame_fetcher = frame_fetcher
        self._lock = threading.Lock()
        self._cache_lock = threading.Lock()
        self._active_session: Optional[OfflineSession] = None
        self._orphans: list[OfflineSession] = []
        self._offline_point_req_count: dict[object, int] = {}
        self._last_focus_anchor: Optional[Tuple[int, int]] = None
        self._last_roi2_rect: Optional[Tuple[int, int, int, int]] = None
        self._last_roi3_rect: Optional[Tuple[int, int, int, int]] = None

    def _frame_diag(self, frame: Optional[FrameSnapshot]) -> dict:
        if frame is None:
            return {"frame_available": False}
        payload = {
            "frame_available": True,
            "frame_seq": int(frame.seq),
            "frame_ts": round(float(frame.ts), 6),
            "frame_shape": [int(v) for v in frame.image.shape],
        }
        return payload

    def _session_diag(self, session: Optional[OfflineSession]) -> dict:
        if session is None:
            return {"session_active": False}
        return {
            "session_active": True,
            "point_id": session.point_id,
            "before_seq": int(session.before_seq) if session.before_seq is not None else None,
            "before_ts": round(float(session.before_ts), 6) if session.before_ts is not None else None,
            "focus_anchor": [int(session.focus_anchor[0]), int(session.focus_anchor[1])] if session.focus_anchor is not None else None,
            "focus_depth_mm": round(float(session.focus_depth_mm), 6) if session.focus_depth_mm is not None else None,
            "roi2_rect": [int(v) for v in session.roi2_rect] if session.roi2_rect is not None else None,
            "roi3_rect": [int(v) for v in session.roi3_rect] if session.roi3_rect is not None else None,
            "before_mean": round(float(session.before_mean), 6) if session.before_mean is not None else None,
            "debug_dir": session.debug_dir,
        }

    def _offline_diag(self, event: str, level: str = "info", **fields) -> None:
        payload = {"event": event}
        payload.update(fields)
        payload["capture_source"] = self._capture_source
        getattr(self._logger, level, self._logger.info)("OFFLINE diag %s: %s", event, safe_json_text(payload))

    def _elapsed_ms_since(self, start_ns: Optional[int], now_ns: Optional[int] = None) -> Optional[float]:
        if start_ns is None:
            return None
        if now_ns is None:
            now_ns = time.perf_counter_ns()
        return round(float(now_ns - int(start_ns)) / 1_000_000.0, 3)

    def _finalization_progress_fields(self, session: OfflineSession, now_ns: Optional[int] = None) -> dict:
        if now_ns is None:
            now_ns = time.perf_counter_ns()
        fields = {}
        if session.finalization_stage is not None:
            fields["last_stage"] = session.finalization_stage
        last_stage_elapsed_ms = self._elapsed_ms_since(session.finalization_stage_started_ns, now_ns)
        if last_stage_elapsed_ms is not None:
            fields["last_stage_elapsed_ms"] = last_stage_elapsed_ms
        finalization_elapsed_ms = self._elapsed_ms_since(session.finalization_started_ns, now_ns)
        if finalization_elapsed_ms is not None:
            fields["finalization_elapsed_ms"] = finalization_elapsed_ms
        return fields

    def _finalization_common_fields(self, session: OfflineSession, now_ns: Optional[int] = None) -> dict:
        fields = self._finalization_progress_fields(session, now_ns)
        fields.update(
            {
                "before_set": bool(session.before is not None),
                "after_set": bool(session.after is not None),
                "frame_buffer_count": len(session.frame_buffer),
                "debug_save_enabled": bool(self._config.debug_save_enabled),
            }
        )
        return fields

    def _finalization_stage_begin(self, session: OfflineSession, stage: str, **fields) -> int:
        now_ns = time.perf_counter_ns()
        if session.finalization_started_ns is None:
            session.finalization_started_ns = now_ns
        session.finalization_stage = stage
        session.finalization_stage_started_ns = now_ns
        payload = {"stage": stage}
        payload.update(self._finalization_common_fields(session, now_ns))
        payload.update(fields)
        self._offline_diag(f"{stage}_begin", point_id=session.point_id, **payload)
        return now_ns

    def _finalization_stage_end(self, session: OfflineSession, stage: str, start_ns: int, **fields) -> None:
        now_ns = time.perf_counter_ns()
        payload = {
            "stage": stage,
            "elapsed_ms": self._elapsed_ms_since(start_ns, now_ns),
        }
        payload.update(self._finalization_common_fields(session, now_ns))
        payload.update(fields)
        self._offline_diag(f"{stage}_end", point_id=session.point_id, **payload)

    def _mark_finished_event_set(self, session: OfflineSession, reason: str) -> None:
        now_ns = time.perf_counter_ns()
        if session.finalization_started_ns is None:
            session.finalization_started_ns = now_ns
        session.finalization_stage = "finished_event_set"
        session.finalization_stage_started_ns = now_ns
        response = session.response if isinstance(session.response, dict) else {}
        self._offline_diag(
            "finished_event_set",
            point_id=session.point_id,
            reason=reason,
            response_success=response.get("success"),
            response_info=response.get("info"),
            **self._finalization_common_fields(session, now_ns),
        )
        session.finished_event.set()

    def _parse_arg(self, arg_json_text: Optional[str]) -> dict:
        if not arg_json_text:
            raise ValueError("OFFLINE requires JSON args")
        obj = json.loads(arg_json_text)
        if not isinstance(obj, dict):
            raise ValueError("OFFLINE args must be JSON object")
        return obj

    def _normalize_point_key(self, point_id):
        try:
            return int(point_id)
        except Exception:
            return point_id

    def _prune_orphans_locked(self) -> None:
        self._orphans = [s for s in self._orphans if s.thread is not None and s.thread.is_alive()][-8:]

    def _get_cached_roi_state(self):
        with self._cache_lock:
            return self._last_focus_anchor, self._last_roi2_rect, self._last_roi3_rect

    def _set_cached_roi_state(self, anchor, roi2_rect, roi3_rect) -> None:
        with self._cache_lock:
            self._last_focus_anchor = anchor
            self._last_roi2_rect = roi2_rect
            self._last_roi3_rect = roi3_rect

    def handle(self, arg_json_text: Optional[str]) -> dict:
        arg_obj = self._parse_arg(arg_json_text)
        point_id = arg_obj.get("point_id")
        if point_id is None:
            return {"success": False, "info": "missing_point_id"}
        if "time_out" not in arg_obj:
            return {"success": False, "info": "missing_time_out", "point_id": point_id}
        if "is_save" not in arg_obj:
            return {"success": False, "info": "missing_is_save", "point_id": point_id}
        try:
            duration_s = float(arg_obj["time_out"])
        except Exception:
            return {"success": False, "info": "invalid_time_out", "point_id": point_id}
        is_save = bool(arg_obj["is_save"])

        with self._lock:
            self._prune_orphans_locked()
            active = self._active_session
            point_key = self._normalize_point_key(point_id)
            accepted = int(self._offline_point_req_count.get(point_key, 0))
            if accepted >= 2:
                return {"success": False, "info": "offline_ignored_extra_request", "point_id": point_id}
            self._offline_diag(
                "handle",
                point_id=point_id,
                action="stop" if active is not None and active.point_id == point_id else "start",
                capture_source="image_matrix",
                active_session_count=1 if active is not None else 0,
            )
            if active is not None and active.point_id == point_id:
                self._offline_point_req_count[point_key] = accepted + 1
                return self._stop_locked(active)
            if active is not None:
                active.stop_event.set()
                self._offline_diag(
                    "switch_wait_begin",
                    point_id=point_id,
                    previous_point_id=active.point_id,
                    capture_source="image_matrix",
                    capture_done_before_wait=bool(active.capture_done_event.is_set()),
                    thread_alive_before_wait=bool(active.thread is not None and active.thread.is_alive()),
                )
                try:
                    active.capture_done_event.wait(timeout=2)
                except Exception:
                    pass
                try:
                    if active.thread is not None and active.thread.is_alive() and (not active.capture_done_event.is_set()):
                        active.thread.join(timeout=5)
                except Exception:
                    pass
                self._offline_diag(
                    "switch_wait_completed",
                    point_id=point_id,
                    previous_point_id=active.point_id,
                    capture_source="image_matrix",
                    capture_done_after_wait=bool(active.capture_done_event.is_set()),
                    thread_alive_after_wait=bool(active.thread is not None and active.thread.is_alive()),
                )
                self._orphans.append(active)
                self._active_session = None
            self._offline_point_req_count[point_key] = accepted + 1
            return self._start_locked(point_id, duration_s, is_save)

    def _start_locked(self, point_id, duration_s: float, is_save: bool) -> dict:
        debug_dir = None
        if self._config.debug_save_enabled:
            debug_dir = self._debug_saver.create_session_dir(self._config.debug_save_dir, point_id)
        session = OfflineSession(
            point_id=point_id,
            duration_s=duration_s,
            is_save=is_save,
            stop_event=threading.Event(),
            debug_dir=debug_dir,
            meta={"point_id": point_id, "duration_s": duration_s, "is_save": bool(is_save)},
        )
        session.thread = threading.Thread(target=self._run_session, args=(session,), daemon=True, name=f"pywrapper-offline-{point_id}")
        self._active_session = session
        self._offline_diag(
            "start_completed",
            point_id=point_id,
            capture_source="image_matrix",
            debug_save_enabled=bool(self._config.debug_save_enabled),
            debug_dir=debug_dir,
            duration_s=round(float(duration_s), 6),
            is_save=bool(is_save),
            peak_detect_enabled=bool(self._config.peak_detect_enabled),
            offline_peak_enabled=bool(self._config.offline_peak_enabled),
        )
        session.thread.start()
        self._offline_diag(
            "start_thread_started",
            point_id=point_id,
            capture_source="image_matrix",
            thread_name=session.thread.name if session.thread is not None else None,
            duration_s=round(float(duration_s), 6),
            is_save=bool(is_save),
        )
        result = {"success": True, "info": "offline_started", "point_id": point_id}
        if debug_dir is not None:
            result["debug_dir"] = debug_dir
        return result

    def _stop_locked(self, session: OfflineSession) -> dict:
        session.stop_event.set()
        timeout_s = max(1.0, min(float(self._config.stop_wait_timeout_seconds), 120.0))
        self._offline_diag(
            "stop_wait_begin",
            point_id=session.point_id,
            capture_source="image_matrix",
            wait_timeout_s=round(float(timeout_s), 6),
            thread_alive=bool(session.thread is not None and session.thread.is_alive()),
            **self._finalization_progress_fields(session),
        )
        finished_ok = bool(session.finished_event.wait(timeout=timeout_s))
        self._offline_diag(
            "stop_wait_completed",
            point_id=session.point_id,
            capture_source="image_matrix",
            wait_timeout_s=round(float(timeout_s), 6),
            finished_ok=bool(finished_ok),
            capture_done=bool(session.capture_done_event.is_set()),
            thread_alive=bool(session.thread is not None and session.thread.is_alive()),
            **self._finalization_progress_fields(session),
        )
        self._active_session = None
        self._orphans.append(session)
        response = dict(session.response or {})
        if response.get("success") is False:
            return response
        result = {
            "success": True,
            "info": "offline_stop_completed" if finished_ok else "offline_stop_timeout",
            "point_id": session.point_id,
            "roi2_color": "green" if str(session.final_roi2_color).strip().lower() == "green" else "red",
            "roi2_final": bool(finished_ok),
        }
        for key, value in response.items():
            if key not in {"success", "info", "point_id"}:
                result[key] = value
        self._offline_diag(
            "stop_response_ready",
            point_id=session.point_id,
            capture_source="image_matrix",
            response=safe_json_text(result),
        )
        return result

    def _append_frame_buffer(self, session: OfflineSession, frame: np.ndarray, seq: int, ts: float, frame_index: int, tag: str, roi1_gray: float) -> None:
        session.frame_buffer.append(OfflineFrameRecord(np.array(frame, copy=True), int(seq), float(ts), int(frame_index), str(tag), float(roi1_gray)))
        limit = max(1, int(self._config.offline_tmp_max_buffer_frames))
        if len(session.frame_buffer) > limit:
            session.frame_buffer = session.frame_buffer[-limit:]

    def _select_before_record_for_roi2(self, session: OfflineSession, record: OfflineFrameRecord, reason: str) -> None:
        session.before = np.array(record.frame, copy=True)
        session.before_seq = int(record.seq)
        session.before_ts = float(record.ts)
        session.before_name = format_frame_timestamp(record.ts)
        if session.roi2_rect is None:
            self._initialize_focus_and_rois(session, session.before)
        session.before_mean = roi_gray_mean(session.before, session.roi2_rect) if session.roi2_rect is not None else None
        self._offline_diag(
            "before_selected",
            point_id=session.point_id,
            capture_source="image_matrix",
            frame_index=int(record.frame_index),
            frame_seq=int(record.seq),
            frame_ts=round(float(record.ts), 6),
            before_name=session.before_name,
            before_method=reason,
            roi1_gray=round(float(record.roi1_gray), 6),
            roi2_before_mean=round(float(session.before_mean), 6) if session.before_mean is not None else None,
        )

    def _select_after_record_for_roi2(self, session: OfflineSession, record: OfflineFrameRecord, reason: str) -> None:
        session.after = np.array(record.frame, copy=True)
        session.after_seq = int(record.seq)
        session.after_ts = float(record.ts)
        session.after_name = format_frame_timestamp(record.ts)
        session.after_method = reason
        self._offline_diag(
            "after_selected",
            point_id=session.point_id,
            capture_source="image_matrix",
            frame_index=int(record.frame_index),
            frame_seq=int(record.seq),
            frame_ts=round(float(record.ts), 6),
            after_name=session.after_name,
            after_method=session.after_method,
            roi1_gray=round(float(record.roi1_gray), 6),
        )

    def _find_roi1_core_interval(
        self,
        records: list[OfflineFrameRecord],
        active_threshold: float,
    ) -> tuple[int, int]:
        intervals: list[tuple[int, int]] = []
        start = None
        inactive_run = 0
        for index, record in enumerate(records):
            is_active = float(record.roi1_gray) >= float(active_threshold)
            if is_active and start is None:
                start = index
                inactive_run = 0
            elif is_active:
                inactive_run = 0
            elif start is not None:
                inactive_run += 1
                if inactive_run > ROI1_BOUNDARY_MAX_INACTIVE_GAP:
                    intervals.append((start, index - inactive_run))
                    start = None
                    inactive_run = 0
        if start is not None:
            tail_trim = inactive_run if inactive_run > 0 else 0
            intervals.append((start, len(records) - 1 - tail_trim))
        if len(intervals) != 1:
            raise ValueError(f"OFFLINE expected exactly one ROI1 active interval, found {len(intervals)}")
        return intervals[0]

    def _apply_roi1_boundary_selection(self, session: OfflineSession, before_gray_mean: float) -> None:
        records = list(session.frame_buffer)
        if not records:
            raise ValueError("OFFLINE requires buffered frames for ROI1 boundary selection")
        active_threshold = float(before_gray_mean) + float(self._config.offline_peak_threshold or 0.0)
        active_extension_threshold = float(before_gray_mean) + ROI1_BOUNDARY_ACTIVE_EXTENSION_OFFSET
        return_to_baseline_threshold = float(before_gray_mean) + ROI1_BOUNDARY_RETURN_TO_BASELINE_OFFSET
        core_start, core_end = self._find_roi1_core_interval(records, active_threshold)
        active_start = core_start
        active_end = core_end
        while active_start > 0 and float(records[active_start - 1].roi1_gray) >= active_extension_threshold:
            active_start -= 1
        while active_end + 1 < len(records) and float(records[active_end + 1].roi1_gray) > return_to_baseline_threshold:
            active_end += 1
        before_index = active_start - ROI1_BOUNDARY_OFFSET
        if before_index < 0:
            raise ValueError("OFFLINE requires at least two frames before treatment active interval")
        after_index = active_end + ROI1_BOUNDARY_OFFSET
        after_fallback_used = False
        if after_index >= len(records):
            after_index = len(records) - 1
            after_fallback_used = True
        self._select_before_record_for_roi2(session, records[before_index], "roi1_boundary_before2")
        after_reason = "roi1_boundary_after2_fallback_last" if after_fallback_used else "roi1_boundary_after2"
        self._select_after_record_for_roi2(session, records[after_index], after_reason)
        self._append_frame_buffer(
            session,
            records[after_index].frame,
            records[after_index].seq,
            records[after_index].ts,
            records[after_index].frame_index,
            "after_boundary2",
            records[after_index].roi1_gray,
        )
        self._offline_diag(
            "roi1_boundary_interval_selected",
            point_id=session.point_id,
            capture_source="image_matrix",
            core_start_index=int(records[core_start].frame_index),
            core_end_index=int(records[core_end].frame_index),
            active_start_index=int(records[active_start].frame_index),
            active_end_index=int(records[active_end].frame_index),
            before_index=int(records[before_index].frame_index),
            after_index=int(records[after_index].frame_index),
            active_threshold=round(float(active_threshold), 6),
            active_extension_threshold=round(float(active_extension_threshold), 6),
            return_to_baseline_threshold=round(float(return_to_baseline_threshold), 6),
            after_fallback_used=bool(after_fallback_used),
        )

    def _initialize_focus_and_rois(self, session: OfflineSession, before_frame: np.ndarray) -> None:
        raw_provider = self._provider_fetcher()
        focus_point = raw_provider.get("focus_point") if isinstance(raw_provider, dict) else None
        provider_depth = raw_provider.get("depth") if isinstance(raw_provider, dict) else None
        focus_depth_mm = parse_focus_depth_mm(provider_depth)
        anchor = parse_focus_point(focus_point) if focus_point is not None else None
        roi2_rect = None
        roi3_rect = None
        used_cache = False
        if anchor is not None:
            height, width = before_frame.shape[:2]
            roi2_rect = compute_roi_region((width, height), anchor, self._config.roi2_extension_params)
            roi3_rect = compute_roi_region((width, height), anchor, self._config.roi3_extension_params)
        if anchor is None or roi2_rect is None or roi3_rect is None:
            cached_anchor, cached_roi2, cached_roi3 = self._get_cached_roi_state()
            if cached_anchor is not None and cached_roi2 is not None and cached_roi3 is not None:
                anchor, roi2_rect, roi3_rect = cached_anchor, cached_roi2, cached_roi3
                used_cache = True
        if anchor is not None and roi2_rect is not None and roi3_rect is not None:
            session.focus_anchor = anchor
            session.focus_depth_mm = focus_depth_mm
            session.roi2_rect = roi2_rect
            session.roi3_rect = roi3_rect
            self._set_cached_roi_state(anchor, roi2_rect, roi3_rect)
        session.meta["provider_focus_point"] = focus_point
        session.meta["provider_depth"] = provider_depth
        session.meta["focus_depth_mm"] = focus_depth_mm
        self._offline_diag(
            "focus_roi_initialized",
            point_id=session.point_id,
            capture_source="image_matrix",
            provider_focus_point=focus_point,
            provider_depth=provider_depth,
            focus_depth_mm=focus_depth_mm,
            parsed_anchor=[int(anchor[0]), int(anchor[1])] if anchor is not None else None,
            used_cache=bool(used_cache),
            roi2_rect=[int(v) for v in roi2_rect] if roi2_rect is not None else None,
            roi3_rect=[int(v) for v in roi3_rect] if roi3_rect is not None else None,
        )

    def _select_override_frame(self, session: OfflineSession, use_peak_max: bool):
        if use_peak_max and self._config.debug_save_enabled and session.frame_buffer and session.roi3_rect is not None:
            best_record = None
            best_metrics = None
            for record in session.frame_buffer:
                metrics = compute_roi3_metrics(record.frame, session.roi3_rect)
                if metrics.get("g1") is None:
                    continue
                if best_metrics is None or float(metrics["g1"]) > float(best_metrics["g1"]):
                    best_record = record
                    best_metrics = metrics
            if best_record is not None:
                return best_record.frame, best_record.frame_index, best_record.tag, best_metrics
        if session.after is None or session.roi3_rect is None:
            return None, None, None, {"roi3_mean": None, "g1": None, "g2": None, "column_diff": None}
        return session.after, None, "after", compute_roi3_metrics(session.after, session.roi3_rect)

    def _apply_roi4_after_selector_if_needed(self, session: OfflineSession) -> None:
        selector = dict(self._config.roi4_after_selector or {})
        if not bool(selector.get("enabled", False)):
            self._offline_diag(
                "roi4_after_selector_skip",
                point_id=session.point_id,
                capture_source="image_matrix",
                reason="disabled",
                after_method=session.after_method,
            )
            return
        if session.after_method not in ROI4_FALLBACK_AFTER_METHODS:
            self._offline_diag(
                "roi4_after_selector_skip",
                point_id=session.point_id,
                capture_source="image_matrix",
                reason="after_method_not_fallback",
                after_method=session.after_method,
                fallback_methods=sorted(ROI4_FALLBACK_AFTER_METHODS),
            )
            return
        try:
            if self._config.roi4_rect is None:
                raise ValueError("ROI4 after selector requires roi4_rect")
            if session.initial_before_record is None:
                raise ValueError("ROI4 after selector requires initial before frame")
            if not session.frame_buffer:
                raise ValueError("ROI4 after selector requires buffered frames")

            block_size = int(selector.get("block_size", 24))
            gray_diff_threshold = float(selector.get("gray_diff_threshold", 15.0))
            area_threshold = float(selector.get("candidate_area_ratio_threshold", 3.0))
            descent_low_frame_number = int(selector.get("descent_low_frame_number", 2))
            if block_size <= 0:
                raise ValueError("ROI4 block_size must be > 0")
            if gray_diff_threshold <= 0.0:
                raise ValueError("ROI4 gray_diff_threshold must be > 0")
            if area_threshold <= 0.0:
                raise ValueError("ROI4 candidate_area_ratio_threshold must be > 0")
            if descent_low_frame_number <= 0:
                raise ValueError("ROI4 descent_low_frame_number must be > 0")

            baseline = session.initial_before_record
            self._offline_diag(
                "roi4_after_selector_begin",
                point_id=session.point_id,
                capture_source="image_matrix",
                original_after_method=session.after_method,
                original_after_seq=int(session.after_seq) if session.after_seq is not None else None,
                configured_roi4_rect=[int(v) for v in self._config.roi4_rect],
                baseline_frame_index=int(baseline.frame_index),
                baseline_seq=int(baseline.seq),
                buffered_frame_count=len(session.frame_buffer),
                block_size=int(block_size),
                gray_diff_threshold=round(float(gray_diff_threshold), 6),
                candidate_area_ratio_threshold=round(float(area_threshold), 6),
                descent_low_frame_number=int(descent_low_frame_number),
            )
            roi4_rect = validate_roi4_rect_for_image(self._config.roi4_rect, baseline.frame)
            session.roi4_rect = roi4_rect
            session.roi4_candidate_area_ratio_threshold = area_threshold
            session.roi4_after_selector_applied = False
            session.roi4_after_frame_index = None
            session.roi4_after_method = None
            session.roi4_selector_reason = "no_low_high_low_sequence"

            seen_low_before_high = False
            seen_high = False
            low_after_high_count = 0
            selected_record = None
            selected_metrics = None
            last_metrics = None
            scanned_frame_count = 0

            for record in session.frame_buffer:
                if int(record.frame_index) <= int(baseline.frame_index):
                    continue
                scanned_frame_count += 1
                metrics = compute_roi4_mask_metrics(
                    baseline.frame,
                    record.frame,
                    roi4_rect,
                    block_size=block_size,
                    gray_diff_threshold=gray_diff_threshold,
                )
                last_metrics = metrics
                ratio = float(metrics["candidate_area_ratio"])
                if not seen_high:
                    if ratio < area_threshold:
                        if not seen_low_before_high:
                            self._offline_diag(
                                "roi4_after_selector_initial_low",
                                point_id=session.point_id,
                                capture_source="image_matrix",
                                frame_index=int(record.frame_index),
                                frame_seq=int(record.seq),
                                candidate_area_ratio=round(float(ratio), 6),
                                candidate_area_ratio_threshold=round(float(area_threshold), 6),
                            )
                        seen_low_before_high = True
                        continue
                    if seen_low_before_high and ratio >= area_threshold:
                        seen_high = True
                        low_after_high_count = 0
                        self._offline_diag(
                            "roi4_after_selector_high_enter",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            frame_index=int(record.frame_index),
                            frame_seq=int(record.seq),
                            candidate_area_ratio=round(float(ratio), 6),
                            candidate_area_ratio_threshold=round(float(area_threshold), 6),
                            candidate_block_count=int(metrics["candidate_block_count"]),
                            largest_area_ratio=round(float(metrics["largest_area_ratio"]), 6),
                            largest_mean_diff=round(float(metrics["largest_mean_diff"]), 6),
                            max_diff=round(float(metrics["max_diff"]), 6),
                        )
                    continue

                if ratio < area_threshold:
                    low_after_high_count += 1
                    self._offline_diag(
                        "roi4_after_selector_descent_low",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(record.frame_index),
                        frame_seq=int(record.seq),
                        candidate_area_ratio=round(float(ratio), 6),
                        candidate_area_ratio_threshold=round(float(area_threshold), 6),
                        low_after_high_count=int(low_after_high_count),
                        target_low_count=int(descent_low_frame_number),
                    )
                    if low_after_high_count >= descent_low_frame_number:
                        selected_record = record
                        selected_metrics = metrics
                        break
                else:
                    if low_after_high_count > 0:
                        self._offline_diag(
                            "roi4_after_selector_descent_reset",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            frame_index=int(record.frame_index),
                            frame_seq=int(record.seq),
                            candidate_area_ratio=round(float(ratio), 6),
                            previous_low_after_high_count=int(low_after_high_count),
                        )
                    low_after_high_count = 0

            if selected_record is None:
                if last_metrics is not None:
                    session.roi4_candidate_area_ratio = float(last_metrics["candidate_area_ratio"])
                self._offline_diag(
                    "roi4_after_selector_no_match",
                    point_id=session.point_id,
                    capture_source="image_matrix",
                    reason="no_low_high_low_sequence",
                    scanned_frame_count=int(scanned_frame_count),
                    seen_low_before_high=bool(seen_low_before_high),
                    seen_high=bool(seen_high),
                    low_after_high_count=int(low_after_high_count),
                    last_candidate_area_ratio=round(float(session.roi4_candidate_area_ratio), 6) if session.roi4_candidate_area_ratio is not None else None,
                    candidate_area_ratio_threshold=round(float(area_threshold), 6),
                )
                return

            session.before = np.array(baseline.frame, copy=True)
            session.before_seq = int(baseline.seq)
            session.before_ts = float(baseline.ts)
            session.before_name = format_frame_timestamp(baseline.ts)
            session.after = np.array(selected_record.frame, copy=True)
            session.after_seq = int(selected_record.seq)
            session.after_ts = float(selected_record.ts)
            session.after_name = format_frame_timestamp(selected_record.ts)
            session.after_method = "roi4_mask_descent_second"
            session.before_mean = None
            session.after_mean = None
            session.roi2_diff = None
            session.roi4_after_selector_applied = True
            session.roi4_after_frame_index = int(selected_record.frame_index)
            session.roi4_after_method = session.after_method
            session.roi4_candidate_area_ratio = float(selected_metrics["candidate_area_ratio"]) if selected_metrics is not None else None
            session.roi4_selector_reason = "selected"
            self._offline_diag(
                "roi4_after_selected",
                point_id=session.point_id,
                capture_source="image_matrix",
                roi4_rect=[int(v) for v in roi4_rect],
                frame_index=int(selected_record.frame_index),
                frame_seq=int(selected_record.seq),
                frame_ts=round(float(selected_record.ts), 6),
                candidate_area_ratio=round(float(session.roi4_candidate_area_ratio), 6) if session.roi4_candidate_area_ratio is not None else None,
                candidate_area_ratio_threshold=round(float(area_threshold), 6),
                block_size=int(block_size),
                gray_diff_threshold=round(float(gray_diff_threshold), 6),
            )
        except Exception as exc:
            self._offline_diag(
                "roi4_after_selector_failed",
                level="error",
                point_id=session.point_id,
                capture_source="image_matrix",
                after_method=session.after_method,
                configured_roi4_rect=[int(v) for v in self._config.roi4_rect] if self._config.roi4_rect is not None else None,
                error=str(exc),
            )
            raise

    def _apply_roi3_overrides(self, session: OfflineSession) -> None:
        if session.final_roi2_color != "red" or session.roi3_rect is None:
            return
        g1g2_conf = dict(self._config.roi3_g1_g2_override or {})
        frame, frame_index, tag, metrics = self._select_override_frame(session, bool(g1g2_conf.get("use_peak_max", True)))
        session.roi3_g1 = metrics.get("g1")
        session.roi3_g2 = metrics.get("g2")
        session.roi3_column_diff = metrics.get("column_diff")
        if bool(g1g2_conf.get("enabled", True)) and session.roi3_g1 is not None and session.roi3_g2 is not None:
            if float(session.roi3_g1) > float(g1g2_conf.get("g1_threshold", 98.0)) and float(session.roi3_g2) > float(g1g2_conf.get("g2_threshold", 20.0)):
                session.final_roi2_color = "green"
                session.roi3_override_applied = True
                session.roi3_override_method = "roi3_g1_g2"
                session.roi3_override_frame_index = frame_index
                session.roi3_override_tag = tag
                return
        col_conf = dict(self._config.roi3_column_diff_override or {})
        frame, frame_index, tag, metrics = self._select_override_frame(session, bool(col_conf.get("use_peak_max", True)))
        session.roi3_g1 = metrics.get("g1")
        session.roi3_g2 = metrics.get("g2")
        session.roi3_column_diff = metrics.get("column_diff")
        if bool(col_conf.get("enabled", True)) and session.roi3_g1 is not None and session.roi3_column_diff is not None:
            if float(session.roi3_g1) > float(col_conf.get("g1_threshold", 99.0)) and float(session.roi3_column_diff) > float(col_conf.get("threshold", 15.0)):
                session.final_roi2_color = "green"
                session.roi3_override_applied = True
                session.roi3_override_method = "roi3_column_diff"
                session.roi3_override_frame_index = frame_index
                session.roi3_override_tag = tag

    def _flush_buffered_frames(self, session: OfflineSession) -> None:
        if not self._config.debug_save_enabled or not session.debug_dir or not session.frame_buffer:
            return
        meta_jsonl = Path(session.debug_dir) / "offline_frames_meta.jsonl"
        before_written = False
        after_written = False
        self._offline_diag(
            "buffer_flush_begin",
            point_id=session.point_id,
            capture_source="image_matrix",
            buffered_frame_count=len(session.frame_buffer),
            debug_dir=session.debug_dir,
            meta_jsonl=str(meta_jsonl),
        )
        for record in session.frame_buffer:
            name = format_buffered_frame_name(record.frame_index, record.ts, record.tag)
            out_path = Path(session.debug_dir) / name
            write_png(out_path, record.frame)
            roi2_mean = roi_gray_mean(record.frame, session.roi2_rect) if session.roi2_rect is not None else None
            roi3_mean = roi_gray_mean(record.frame, session.roi3_rect) if session.roi3_rect is not None else None
            write_jsonl_line(
                meta_jsonl,
                {
                    "filename": name,
                    "roi1_mean": record.roi1_gray,
                    "roi2_mean": roi2_mean,
                    "roi3_mean": roi3_mean,
                },
            )
            if (
                (not before_written)
                and session.before_seq is not None
                and int(record.seq) == int(session.before_seq)
                and (session.before_ts is None or abs(float(record.ts) - float(session.before_ts)) < 0.000001)
            ):
                write_jsonl_line(
                    meta_jsonl,
                    {
                        "event": "before_saved",
                        "filename": name,
                        "point_id": session.point_id,
                        "frame_index": record.frame_index,
                        "ts": format_frame_timestamp(record.ts),
                        "tag": record.tag,
                    },
                )
                before_written = True
            if (not after_written) and str(record.tag).startswith("after"):
                write_jsonl_line(
                    meta_jsonl,
                    {
                        "event": "after_saved",
                        "filename": name,
                        "point_id": session.point_id,
                        "frame_index": record.frame_index,
                        "ts": format_frame_timestamp(record.ts),
                        "tag": record.tag,
                    },
                )
                after_written = True
        self._offline_diag(
            "buffer_flush_completed",
            point_id=session.point_id,
            capture_source="image_matrix",
            buffered_frame_count=len(session.frame_buffer),
            before_event_written=bool(before_written),
            after_event_written=bool(after_written),
            debug_dir=session.debug_dir,
            meta_jsonl=str(meta_jsonl),
        )

    def _save_debug_outputs(self, session: OfflineSession) -> None:
        if not self._config.debug_save_enabled or not session.debug_dir:
            return
        self._flush_buffered_frames(session)
        meta = dict(session.meta)
        meta["focus_anchor"] = [int(session.focus_anchor[0]), int(session.focus_anchor[1])] if session.focus_anchor is not None else None
        meta["focus_depth_mm"] = round(float(session.focus_depth_mm), 6) if session.focus_depth_mm is not None else None
        meta["focus_y_offset_mm"] = round(float(self._config.focus_y_offset_mm), 6)
        focus_overlay_anchor = None
        if session.before is not None:
            focus_overlay_anchor = resolve_focus_overlay_anchor(
                (int(session.before.shape[1]), int(session.before.shape[0])),
                session,
                self._config,
            )
        meta["focus_overlay_anchor"] = [int(focus_overlay_anchor[0]), int(focus_overlay_anchor[1])] if focus_overlay_anchor is not None else None
        meta["roi2_rect"] = [int(v) for v in session.roi2_rect] if session.roi2_rect is not None else None
        meta["roi3_rect"] = [int(v) for v in session.roi3_rect] if session.roi3_rect is not None else None
        meta.update(build_roi4_diagnostics(session))
        if session.before is not None and session.roi2_rect is not None and session.roi3_rect is not None:
            self._debug_saver.save_stage(session.debug_dir, "before", session.before, session.roi2_rect, session.roi3_rect)
            write_png(Path(session.debug_dir) / "final_before.png", session.before)
        if session.after is not None and session.roi2_rect is not None and session.roi3_rect is not None:
            self._debug_saver.save_stage(session.debug_dir, "after", session.after, session.roi2_rect, session.roi3_rect)
            write_png(Path(session.debug_dir) / "final_after.png", session.after)
        if session.before is not None and session.after is not None:
            diff_with_overlay = render_diff_with_overlay(session, self._config)
            if diff_with_overlay is not None:
                write_png(Path(session.debug_dir) / "final_differ.png", diff_with_overlay)
        meta["result"] = {
            "roi2_color": session.final_roi2_color,
            "roi2_diff": round(float(session.roi2_diff), 6) if session.roi2_diff is not None else None,
            "roi2_before_mean": round(float(session.before_mean), 6) if session.before_mean is not None else None,
            "roi2_after_mean": round(float(session.after_mean), 6) if session.after_mean is not None else None,
            "roi3_g1": session.roi3_g1,
            "roi3_g2": session.roi3_g2,
            "roi3_column_diff": session.roi3_column_diff,
            "roi3_override_applied": session.roi3_override_applied,
            "roi3_override_method": session.roi3_override_method,
            "roi3_override_frame_index": session.roi3_override_frame_index,
            "roi3_override_tag": session.roi3_override_tag,
            **build_roi4_diagnostics(session),
        }
        self._debug_saver.write_meta(session.debug_dir, meta)

    def _save_final_outputs(self, session: OfflineSession) -> dict:
        stage_start = self._finalization_stage_begin(
            session,
            "save_final_outputs",
            image_output_dir=self._config.image_output_dir,
        )
        result = {}
        img_dir = Path(self._config.image_output_dir) if self._config.image_output_dir else None
        treatment_ok = session.final_roi2_color == "green"
        result_flag_value = "1" if treatment_ok else "0"
        try:
            if img_dir is None:
                return result
            img_dir.mkdir(parents=True, exist_ok=True)
            before_path = img_dir / f"{session.before_name or 'before'}_before.png"
            after_path = img_dir / f"{session.after_name or 'after'}_after.png"
            if not session.is_save:
                before_path = img_dir / "energy_before.png"
                after_path = img_dir / "energy_after.png"
            if session.before is not None:
                write_before_start = self._finalization_stage_begin(session, "write_before", path=str(before_path))
                try:
                    write_png(before_path, render_frame_with_focus_guides(session.before, session, self._config))
                    self._finalization_stage_end(session, "write_before", write_before_start, path=str(before_path), success=True)
                except Exception as exc:
                    self._finalization_stage_end(session, "write_before", write_before_start, path=str(before_path), success=False, error=str(exc))
                    raise
            if session.after is not None:
                write_after_start = self._finalization_stage_begin(session, "write_after", path=str(after_path))
                try:
                    write_png(after_path, render_frame_with_focus_guides(session.after, session, self._config))
                    self._finalization_stage_end(session, "write_after", write_after_start, path=str(after_path), success=True)
                except Exception as exc:
                    self._finalization_stage_end(session, "write_after", write_after_start, path=str(after_path), success=False, error=str(exc))
                    raise
            if session.before is not None:
                result["before_path"] = str(before_path)
            if session.after is not None:
                result["after_path"] = str(after_path)
            if session.before is not None and session.after is not None:
                diff_path = Path(str(after_path).replace("_after", "_diff"))
                render_diff_start = self._finalization_stage_begin(session, "render_diff", path=str(diff_path))
                try:
                    diff_with_overlay = render_diff_with_overlay(session, self._config)
                    self._finalization_stage_end(
                        session,
                        "render_diff",
                        render_diff_start,
                        path=str(diff_path),
                        rendered=bool(diff_with_overlay is not None),
                        success=True,
                    )
                except Exception as exc:
                    self._finalization_stage_end(session, "render_diff", render_diff_start, path=str(diff_path), success=False, error=str(exc))
                    raise
                if diff_with_overlay is not None:
                    write_diff_start = self._finalization_stage_begin(session, "write_diff", path=str(diff_path))
                    try:
                        write_png(diff_path, diff_with_overlay)
                        self._finalization_stage_end(session, "write_diff", write_diff_start, path=str(diff_path), success=True)
                    except Exception as exc:
                        self._finalization_stage_end(session, "write_diff", write_diff_start, path=str(diff_path), success=False, error=str(exc))
                        raise
                result["diff_path"] = str(diff_path)
                self._offline_diag(
                    "main_program_state_sync_begin",
                    point_id=session.point_id,
                    capture_source="image_matrix",
                    roi2_color=session.final_roi2_color,
                    treatment_ok=bool(treatment_ok),
                    result_flag_path=self._config.result_flag_path,
                    result_flag_value=result_flag_value,
                    is_save=bool(session.is_save),
                    db_root_dir=self._config.db_root_dir,
                    before_path=str(before_path),
                    after_path=str(after_path),
                    diff_path=str(diff_path),
                )
                result_flag_start = self._finalization_stage_begin(
                    session,
                    "result_flag_write",
                    path=self._config.result_flag_path,
                    value=result_flag_value,
                )
                try:
                    write_result_flag(self._config.result_flag_path, treatment_ok)
                    self._finalization_stage_end(
                        session,
                        "result_flag_write",
                        result_flag_start,
                        path=self._config.result_flag_path,
                        value=result_flag_value,
                        success=True,
                    )
                    self._offline_diag(
                        "result_flag_written",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        roi2_color=session.final_roi2_color,
                        treatment_ok=bool(treatment_ok),
                        result_flag_path=self._config.result_flag_path,
                        result_flag_value=result_flag_value,
                        value=result_flag_value,
                    )
                except Exception as exc:
                    self._finalization_stage_end(
                        session,
                        "result_flag_write",
                        result_flag_start,
                        path=self._config.result_flag_path,
                        value=result_flag_value,
                        success=False,
                        error=str(exc),
                    )
                    self._logger.exception("OFFLINE result flag write failed: point_id=%s", session.point_id)
                if session.is_save:
                    db_update_start = self._finalization_stage_begin(
                        session,
                        "db_update",
                        db_root_dir=self._config.db_root_dir,
                        before_path=str(before_path),
                        after_path=str(after_path),
                    )
                    try:
                        update_segment_images_info(
                            self._config.db_root_dir,
                            session.point_id,
                            str(before_path),
                            str(after_path),
                            treatment_ok,
                        )
                        self._finalization_stage_end(
                            session,
                            "db_update",
                            db_update_start,
                            db_root_dir=self._config.db_root_dir,
                            before_path=str(before_path),
                            after_path=str(after_path),
                            success=True,
                        )
                        self._offline_diag(
                            "db_update_completed",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            roi2_color=session.final_roi2_color,
                            treatment_ok=bool(treatment_ok),
                            before_path=str(before_path),
                            after_path=str(after_path),
                            db_root_dir=self._config.db_root_dir,
                        )
                    except Exception as exc:
                        self._finalization_stage_end(
                            session,
                            "db_update",
                            db_update_start,
                            db_root_dir=self._config.db_root_dir,
                            before_path=str(before_path),
                            after_path=str(after_path),
                            success=False,
                            error=str(exc),
                        )
                        self._offline_diag(
                            "db_update_failed",
                            level="error",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            roi2_color=session.final_roi2_color,
                            treatment_ok=bool(treatment_ok),
                            before_path=str(before_path),
                            after_path=str(after_path),
                            db_root_dir=self._config.db_root_dir,
                            error=str(exc),
                        )
                        result["db_update_error"] = str(exc)
            self._offline_diag(
                "final_outputs_saved",
                point_id=session.point_id,
                capture_source="image_matrix",
                is_save=bool(session.is_save),
                roi2_color=session.final_roi2_color,
                treatment_ok=bool(treatment_ok),
                result_flag_path=self._config.result_flag_path,
                result_flag_value=result_flag_value,
                output_dir=str(img_dir),
                before_path=result.get("before_path"),
                after_path=result.get("after_path"),
                diff_path=result.get("diff_path"),
            )
            return result
        finally:
            self._finalization_stage_end(
                session,
                "save_final_outputs",
                stage_start,
                image_output_dir=self._config.image_output_dir,
                result_keys=sorted([str(key) for key in result.keys()]),
            )

    def _log_final_response_ready(self, session: OfflineSession) -> None:
        response = session.response if isinstance(session.response, dict) else {}
        roi2_color = response.get("roi2_color", session.final_roi2_color)
        treatment_ok = response.get("treatment_ok")
        if treatment_ok is None:
            treatment_ok = str(roi2_color).strip().lower() == "green"
        self._offline_diag(
            "final_response_ready",
            point_id=session.point_id,
            capture_source="image_matrix",
            response_success=response.get("success"),
            response_info=response.get("info"),
            roi2_color=roi2_color,
            treatment_ok=bool(treatment_ok),
            response_keys=sorted([str(key) for key in response.keys()]),
            before_path=response.get("before_path"),
            after_path=response.get("after_path"),
            diff_path=response.get("diff_path"),
        )

    def _attach_treatment_result_fields(self, session: OfflineSession) -> None:
        if not isinstance(session.response, dict):
            return
        session.response["roi2_color"] = session.final_roi2_color
        session.response["treatment_ok"] = session.final_roi2_color == "green"
        if session.roi2_diff is not None and "roi2_diff" not in session.response:
            session.response["roi2_diff"] = round(float(session.roi2_diff), 6)
        if session.before_mean is not None and "roi2_before_mean" not in session.response:
            session.response["roi2_before_mean"] = round(float(session.before_mean), 6)
        if session.after_mean is not None and "roi2_after_mean" not in session.response:
            session.response["roi2_after_mean"] = round(float(session.after_mean), 6)
        session.response.update(build_roi4_diagnostics(session))

    def _run_session(self, session: OfflineSession) -> None:
        timed_out = False
        last_seq = None
        frame_index = 0
        worker_error_response = None
        before_default = None
        before_default_seq = None
        before_default_ts = None
        before_gray_mean = None
        pending_error_response = None
        deadline_ts = time.time() + float(session.duration_s)
        self._offline_diag(
            "session_thread_enter",
            point_id=session.point_id,
            capture_source="image_matrix",
            duration_s=round(float(session.duration_s), 6),
            is_save=bool(session.is_save),
            debug_save_enabled=bool(self._config.debug_save_enabled),
            peak_detect_enabled=bool(self._config.peak_detect_enabled),
            offline_peak_enabled=bool(self._config.offline_peak_enabled),
            offline_peak_threshold=self._config.offline_peak_threshold,
            offline_peak_end_diff_threshold=round(float(self._config.offline_peak_end_diff_threshold), 6),
            deadline_ts=round(float(deadline_ts), 6),
        )
        try:
            while not session.stop_event.is_set():
                if time.time() >= deadline_ts:
                    timed_out = True
                    session.stop_event.set()
                    self._offline_diag(
                        "session_deadline_reached",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(frame_index),
                        duration_s=round(float(session.duration_s), 6),
                    )
                    break
                if session.after is not None:
                    time.sleep(0.01)
                    continue
                frame = self._frame_fetcher()
                if frame is None or (last_seq is not None and frame.seq == last_seq):
                    time.sleep(0.01)
                    continue
                last_seq = frame.seq
                frame_index += 1
                frame_image = np.array(frame.image, copy=True)
                roi1_gray = frame_gray_mean(frame_image)
                frame_tag = "frame" if self._config.offline_peak_enabled else ("before" if frame_index == 1 else "frame")
                frame_record = OfflineFrameRecord(
                    np.array(frame_image, copy=True),
                    int(frame.seq),
                    float(frame.ts),
                    int(frame_index),
                    frame_tag,
                    float(roi1_gray),
                )
                if before_default is None:
                    before_default = frame_image
                    before_default_seq = frame.seq
                    before_default_ts = frame.ts
                    session.initial_before_record = frame_record
                if session.before is None:
                    session.before = frame_image
                    session.before_seq = frame.seq
                    session.before_ts = frame.ts
                    session.before_name = format_frame_timestamp(frame.ts)
                    before_gray_mean = float(roi1_gray)
                    self._initialize_focus_and_rois(session, frame_image)
                    if session.roi2_rect is not None:
                        session.before_mean = roi_gray_mean(frame_image, session.roi2_rect)
                    self._offline_diag(
                        "before_captured",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_seq=int(frame.seq),
                        frame_ts=round(float(frame.ts), 6),
                        frame_index=int(frame_index),
                        before_name=session.before_name,
                        roi1_gray=round(float(roi1_gray), 6),
                        before_gray_mean=round(float(before_gray_mean), 6),
                        roi2_before_mean=round(float(session.before_mean), 6) if session.before_mean is not None else None,
                    )
                    if self._config.offline_peak_enabled and self._config.offline_peak_threshold is not None:
                        self._offline_diag(
                            "peak_threshold_initialized",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            before_gray_mean=round(float(before_gray_mean), 6),
                            peak_threshold=round(float(before_gray_mean + float(self._config.offline_peak_threshold)), 6),
                            threshold_offset=round(float(self._config.offline_peak_threshold), 6) if self._config.offline_peak_threshold is not None else None,
                        )
                self._append_frame_buffer(session, frame_image, frame.seq, frame.ts, frame_index, frame_record.tag, roi1_gray)
                time.sleep(0.01)
        except Exception as exc:
            self._logger.exception("OFFLINE session worker failed: point_id=%s", session.point_id)
            worker_error_response = {"success": False, "info": "error_in_detect", "point_id": session.point_id, "error": str(exc)}
        finally:
            session.capture_done_event.set()
            if worker_error_response is not None:
                pending_error_response = dict(worker_error_response)
            if session.before is None and before_default is not None:
                session.before = before_default
                session.before_seq = before_default_seq
                session.before_ts = before_default_ts
                session.before_name = format_frame_timestamp(before_default_ts) if before_default_ts is not None else ""
            if self._config.offline_peak_enabled and before_gray_mean is not None and pending_error_response is None:
                try:
                    self._apply_roi1_boundary_selection(session, before_gray_mean)
                except Exception as exc:
                    pending_error_response = {
                        "success": False,
                        "info": "error_in_detect",
                        "point_id": session.point_id,
                        "error": str(exc),
                    }
            if session.after is None and session.stop_event.is_set():
                stop_frame = self._frame_fetcher()
                if stop_frame is not None:
                    session.after = np.array(stop_frame.image, copy=True)
                    session.after_seq = stop_frame.seq
                    session.after_ts = stop_frame.ts
                    session.after_name = format_frame_timestamp(stop_frame.ts)
                    session.after_method = "stop_fallback_timeout" if timed_out else "stop_fallback"
                    try:
                        roi1_gray = frame_gray_mean(session.after)
                    except Exception:
                        roi1_gray = 0.0
                    self._append_frame_buffer(session, session.after, stop_frame.seq, stop_frame.ts, frame_index + 1, "after_stop" if not timed_out else "after_timeout", roi1_gray)
                    self._offline_diag(
                        "after_selected",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(frame_index + 1),
                        frame_seq=int(stop_frame.seq),
                        frame_ts=round(float(stop_frame.ts), 6),
                        after_name=session.after_name,
                        after_method=session.after_method,
                        roi1_gray=round(float(roi1_gray), 6),
                    )
            if session.after is None:
                final_frame = self._frame_fetcher()
                if final_frame is not None:
                    session.after = np.array(final_frame.image, copy=True)
                    session.after_seq = final_frame.seq
                    session.after_ts = final_frame.ts
                    session.after_name = format_frame_timestamp(final_frame.ts)
                    session.after_method = "final_fallback"
                    try:
                        roi1_gray = frame_gray_mean(session.after)
                    except Exception:
                        roi1_gray = 0.0
                    self._append_frame_buffer(session, session.after, final_frame.seq, final_frame.ts, frame_index + 1, "after_final", roi1_gray)
                    self._offline_diag(
                        "after_selected",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(frame_index + 1),
                        frame_seq=int(final_frame.seq),
                        frame_ts=round(float(final_frame.ts), 6),
                        after_name=session.after_name,
                        after_method=session.after_method,
                        roi1_gray=round(float(roi1_gray), 6),
                    )

            self._offline_diag(
                "session_loop_completed",
                point_id=session.point_id,
                capture_source="image_matrix",
                timed_out=bool(timed_out),
                frame_count=int(frame_index),
                before_set=bool(session.before is not None),
                after_set=bool(session.after is not None),
                after_method=session.after_method,
                buffered_frame_count=len(session.frame_buffer),
            )

            self._finalization_stage_begin(session, "postprocess", timed_out=bool(timed_out))
            roi4_validate_start = self._finalization_stage_begin(
                session,
                "roi4_validate",
                configured_roi4_rect=[int(v) for v in self._config.roi4_rect] if self._config.roi4_rect is not None else None,
            )
            try:
                if self._config.roi4_rect is not None and session.before is not None:
                    session.roi4_rect = validate_roi4_rect_for_image(self._config.roi4_rect, session.before)
                self._finalization_stage_end(
                    session,
                    "roi4_validate",
                    roi4_validate_start,
                    success=True,
                    skipped=bool(self._config.roi4_rect is None or session.before is None),
                    roi4_rect=[int(v) for v in session.roi4_rect] if session.roi4_rect is not None else None,
                )
            except Exception as exc:
                self._finalization_stage_end(session, "roi4_validate", roi4_validate_start, success=False, error=str(exc))
                raise
            roi4_selector_start = self._finalization_stage_begin(
                session,
                "roi4_selector",
                after_method=session.after_method,
                selector_enabled=bool((self._config.roi4_after_selector or {}).get("enabled", False)),
            )
            try:
                self._apply_roi4_after_selector_if_needed(session)
                self._finalization_stage_end(
                    session,
                    "roi4_selector",
                    roi4_selector_start,
                    success=True,
                    after_method=session.after_method,
                    applied=bool(session.roi4_after_selector_applied),
                    selector_reason=session.roi4_selector_reason,
                )
            except Exception as exc:
                self._finalization_stage_end(session, "roi4_selector", roi4_selector_start, success=False, error=str(exc))
                pending_error_response = {
                    "success": False,
                    "info": "error_in_detect",
                    "point_id": session.point_id,
                    "error": str(exc),
                }

            roi2_metrics_start = self._finalization_stage_begin(
                session,
                "roi2_metrics",
                peak_detect_enabled=bool(self._config.peak_detect_enabled),
            )
            try:
                session.final_roi2_color = "red"
                if session.roi2_rect is None and session.before is not None:
                    self._initialize_focus_and_rois(session, session.before)
                    if session.roi2_rect is not None and session.before_mean is None:
                        session.before_mean = roi_gray_mean(session.before, session.roi2_rect)
                if self._config.peak_detect_enabled and session.roi2_rect is not None and session.before is not None and session.after is not None:
                    if session.before_mean is None:
                        session.before_mean = roi_gray_mean(session.before, session.roi2_rect)
                    session.after_mean = roi_gray_mean(session.after, session.roi2_rect)
                    session.roi2_diff = float(session.after_mean) - float(session.before_mean)
                    session.final_roi2_color = "green" if session.roi2_diff >= float(self._config.difference_threshold) else "red"
                    if session.final_roi2_color == "red":
                        roi3_override_start = self._finalization_stage_begin(session, "roi3_override")
                        try:
                            self._apply_roi3_overrides(session)
                            self._finalization_stage_end(
                                session,
                                "roi3_override",
                                roi3_override_start,
                                success=True,
                                roi3_override_applied=bool(session.roi3_override_applied),
                                roi3_override_method=session.roi3_override_method,
                            )
                        except Exception as exc:
                            self._finalization_stage_end(session, "roi3_override", roi3_override_start, success=False, error=str(exc))
                            raise
                self._finalization_stage_end(
                    session,
                    "roi2_metrics",
                    roi2_metrics_start,
                    success=True,
                    roi2_color=session.final_roi2_color,
                    roi2_diff=round(float(session.roi2_diff), 6) if session.roi2_diff is not None else None,
                )
            except Exception as exc:
                self._finalization_stage_end(session, "roi2_metrics", roi2_metrics_start, success=False, error=str(exc))
                raise

            self._offline_diag(
                "stop_decision",
                point_id=session.point_id,
                capture_source="image_matrix",
                debug_save_enabled=bool(self._config.debug_save_enabled),
                debug_dir=session.debug_dir,
                before_seq=int(session.before_seq) if session.before_seq is not None else None,
                after_seq=int(session.after_seq) if session.after_seq is not None else None,
                before_ts=round(float(session.before_ts), 6) if session.before_ts is not None else None,
                after_ts=round(float(session.after_ts), 6) if session.after_ts is not None else None,
                roi2_before_mean=round(float(session.before_mean), 6) if session.before_mean is not None else None,
                roi2_after_mean=round(float(session.after_mean), 6) if session.after_mean is not None else None,
                roi2_diff=round(float(session.roi2_diff), 6) if session.roi2_diff is not None else None,
                threshold=round(float(self._config.difference_threshold), 6),
                meets_threshold=bool(session.roi2_diff is not None and session.roi2_diff >= float(self._config.difference_threshold)),
                roi2_color=session.final_roi2_color,
                focus_anchor=[int(session.focus_anchor[0]), int(session.focus_anchor[1])] if session.focus_anchor is not None else None,
                roi2_rect=[int(v) for v in session.roi2_rect] if session.roi2_rect is not None else None,
                roi3_rect=[int(v) for v in session.roi3_rect] if session.roi3_rect is not None else None,
                roi4_rect=[int(v) for v in session.roi4_rect] if session.roi4_rect is not None else None,
                roi4_after_selector_applied=bool(session.roi4_after_selector_applied),
                roi4_after_frame_index=int(session.roi4_after_frame_index) if session.roi4_after_frame_index is not None else None,
                roi4_candidate_area_ratio=round(float(session.roi4_candidate_area_ratio), 6) if session.roi4_candidate_area_ratio is not None else None,
                roi4_candidate_area_ratio_threshold=round(float(session.roi4_candidate_area_ratio_threshold), 6) if session.roi4_candidate_area_ratio_threshold is not None else None,
                frame_shape=[int(v) for v in session.after.shape] if session.after is not None else None,
            )

            try:
                result_paths = self._save_final_outputs(session)
            except Exception:
                self._logger.exception("OFFLINE final output save failed: point_id=%s", session.point_id)
                session.response = {
                    "success": False,
                    "info": "final_output_save_failed",
                    "point_id": session.point_id,
                }
                self._attach_treatment_result_fields(session)
                self._log_final_response_ready(session)
                self._mark_finished_event_set(session, "final_output_save_failed")
                return
            save_debug_start = self._finalization_stage_begin(
                session,
                "save_debug_outputs",
                debug_dir=session.debug_dir,
                debug_save_enabled=bool(self._config.debug_save_enabled),
            )
            try:
                self._save_debug_outputs(session)
                self._finalization_stage_end(
                    session,
                    "save_debug_outputs",
                    save_debug_start,
                    success=True,
                    debug_dir=session.debug_dir,
                    debug_save_enabled=bool(self._config.debug_save_enabled),
                )
            except Exception:
                self._logger.exception("OFFLINE debug save failed on finish: point_id=%s", session.point_id)
                self._finalization_stage_end(
                    session,
                    "save_debug_outputs",
                    save_debug_start,
                    success=False,
                    debug_dir=session.debug_dir,
                    debug_save_enabled=bool(self._config.debug_save_enabled),
                )
                session.response = {
                    "success": False,
                    "info": "debug_save_failed",
                    "point_id": session.point_id,
                }
                self._attach_treatment_result_fields(session)
                self._log_final_response_ready(session)
                self._mark_finished_event_set(session, "debug_save_failed")
                return

            db_update_error = result_paths.pop("db_update_error", None)
            if pending_error_response is not None:
                session.response = dict(pending_error_response)
                session.response.update(result_paths)
                self._attach_treatment_result_fields(session)
                if session.debug_dir is not None:
                    session.response["debug_dir"] = session.debug_dir
                self._log_final_response_ready(session)
                self._mark_finished_event_set(session, "pending_error_response")
                return

            if db_update_error is not None:
                self._logger.error("OFFLINE db update failed: point_id=%s error=%s", session.point_id, db_update_error)
                session.response = {
                    "success": False,
                    "info": "db_update_failed",
                    "point_id": session.point_id,
                    "error": str(db_update_error),
                }
                session.response.update(result_paths)
                self._attach_treatment_result_fields(session)
                if session.debug_dir is not None:
                    session.response["debug_dir"] = session.debug_dir
                self._log_final_response_ready(session)
                self._mark_finished_event_set(session, "db_update_failed")
                return

            session.response = {
                "success": True,
                "info": "offline_stop_completed",
                "point_id": session.point_id,
                "peak_detect_enabled": bool(self._config.peak_detect_enabled),
                "roi2_color": session.final_roi2_color,
                "treatment_ok": session.final_roi2_color == "green",
                "roi2_diff": round(float(session.roi2_diff), 6) if session.roi2_diff is not None else None,
                "roi2_before_mean": round(float(session.before_mean), 6) if session.before_mean is not None else None,
                "roi2_after_mean": round(float(session.after_mean), 6) if session.after_mean is not None else None,
                "focus_anchor": [int(session.focus_anchor[0]), int(session.focus_anchor[1])] if session.focus_anchor is not None else None,
                "roi2_rect": [int(v) for v in session.roi2_rect] if session.roi2_rect is not None else None,
                "roi3_rect": [int(v) for v in session.roi3_rect] if session.roi3_rect is not None else None,
                "before_seq": int(session.before_seq) if session.before_seq is not None else None,
                "after_seq": int(session.after_seq) if session.after_seq is not None else None,
                "after_method": session.after_method,
                "roi3_g1": session.roi3_g1,
                "roi3_g2": session.roi3_g2,
                "roi3_column_diff": session.roi3_column_diff,
                "roi3_override_applied": session.roi3_override_applied,
                "roi3_override_method": session.roi3_override_method,
                "roi3_override_frame_index": session.roi3_override_frame_index,
                "roi3_override_tag": session.roi3_override_tag,
            }
            session.response.update(build_roi4_diagnostics(session))
            session.response.update(result_paths)
            if session.debug_dir is not None:
                session.response["debug_dir"] = session.debug_dir
            self._log_final_response_ready(session)
            self._mark_finished_event_set(session, "offline_stop_completed")


def parse_request(text: str) -> ParsedRequest:
    parts = text.strip().split(";", 2)
    if len(parts) < 2:
        raise ValueError("request must use REQ_TYPE;PASSWORD[;JSON] format")
    req_type = parts[0].strip().upper()
    param = parts[1].strip()
    arg = parts[2].strip() if len(parts) == 3 and parts[2].strip() else None
    if not req_type:
        raise ValueError("request type is empty")
    return ParsedRequest(req_type=req_type, param=param, arg=arg)


def normalize_online_value(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        decimal_value = Decimal(str(value))
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return value
        try:
            decimal_value = Decimal(stripped)
        except InvalidOperation:
            return value
    else:
        return value

    if not decimal_value.is_finite():
        return value
    rounded = decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if rounded == rounded.to_integral_value():
        return int(rounded)
    return float(rounded)


def convert_provider_data(raw_data: dict) -> dict:
    if raw_data is None:
        raise ValueError("Provider fetch returned None")
    if not isinstance(raw_data, dict):
        raise TypeError(f"Provider fetch must return dict, got {type(raw_data).__name__}")

    is_live = raw_data.get("isLive")
    is_freeze = not is_live if is_live is not None else None
    is_hifu = raw_data.get("mode") == 2
    alpha = normalize_online_value(raw_data.get("Alpha"))
    if alpha in (None, ""):
        alpha = 0

    return {
        "SkinDepth": normalize_online_value(raw_data.get("focus_depth")),
        "A": normalize_online_value(raw_data.get("guankuan_a")),
        "B": normalize_online_value(raw_data.get("guankuan_b")),
        "Alpha": alpha,
        "Depth": normalize_online_value(raw_data.get("depth")),
        "IsFreeze": normalize_online_value(is_freeze),
        "isHIFU": is_hifu,
        "FocusPoint": normalize_online_value(raw_data.get("focus_point")),
    }


def json_response(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def safe_json_text(payload) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        return repr(payload)


def online_wall_time() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")


def log_online_timepoint(
    logger: Optional[logging.Logger],
    trace_id: Optional[str],
    step: str,
    **fields,
) -> None:
    if logger is None:
        return
    parts = [
        f"ONLINE timepoint trace_id={trace_id or 'none'}",
        f"step={step}",
        f"wall_time={online_wall_time()}",
        f"perf_counter_ns={time.perf_counter_ns()}",
    ]
    for key, value in fields.items():
        if value is not None:
            parts.append(f"{key}={value}")
    logger.info(" | ".join(parts))


def log_online_diagnostics(
    logger: Optional[logging.Logger],
    raw_data: dict,
    converted_data: dict,
    trace_id: Optional[str] = None,
) -> None:
    if logger is None:
        return

    log_online_timepoint(logger, trace_id, "diagnostics_start")
    logger.info("ONLINE raw provider data: %s", safe_json_text(raw_data))
    logger.info("ONLINE converted response: %s", safe_json_text(converted_data))

    missing_provider_fields = [
        field for field in PROVIDER_FIELDS if not isinstance(raw_data, dict) or raw_data.get(field) is None
    ]
    if missing_provider_fields:
        logger.warning("ONLINE missing provider fields: %s", ", ".join(missing_provider_fields))

    null_response_fields = [
        field for field, value in converted_data.items() if value is None
    ]
    if null_response_fields:
        logger.warning("ONLINE null response fields: %s", ", ".join(null_response_fields))
    log_online_timepoint(
        logger,
        trace_id,
        "diagnostics_completed",
        missing_provider_count=len(missing_provider_fields),
        null_response_count=len(null_response_fields),
    )


def request_type_hint(request_text: str) -> str:
    try:
        return request_text.strip().split(";", 1)[0].strip().upper()
    except Exception:
        return ""


def is_address_in_use_error(exc: OSError) -> bool:
    return getattr(exc, "errno", None) == errno.EADDRINUSE or getattr(exc, "winerror", None) == 10048


def probe_pywrapper_server(host: str, port: int, timeout_s: float = 0.5) -> bool:
    request_bytes = b"ONLINE;bad;{}\n"
    try:
        with socket.create_connection((host, port), timeout=timeout_s) as probe_socket:
            probe_socket.settimeout(timeout_s)
            probe_socket.sendall(request_bytes)
            chunks = []
            while True:
                chunk = probe_socket.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
    except Exception:
        return False

    if not chunks:
        return False

    try:
        response_line = b"".join(chunks).decode("utf-8", errors="strict").splitlines()[0].strip()
        payload = json.loads(response_line)
    except Exception:
        return False
    return isinstance(payload, dict) and payload.get("success") is False and payload.get("info") == "invalid_password"


def build_server_socket(host: str, port: int, logger: Optional[logging.Logger] = None) -> socket.socket:
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        return server_socket
    except OSError as exc:
        try:
            server_socket.close()
        except Exception:
            pass
        if is_address_in_use_error(exc):
            if probe_pywrapper_server(host, port):
                message = f"pywrapper server already running on {host}:{port}"
            else:
                message = f"port {port} on {host} is already occupied by another process"
            if logger is not None:
                logger.error(message)
            raise RuntimeError(message) from exc
        raise


def handle_request(
    request_text: str,
    provider_fetcher: Callable[[], dict],
    logger: Optional[logging.Logger] = None,
    offline_handler: Optional[Callable[[Optional[str]], dict]] = None,
    shutdown_handler: Optional[Callable[[], None]] = None,
    trace_id: Optional[str] = None,
) -> str:
    if request_type_hint(request_text) == "ONLINE":
        log_online_timepoint(logger, trace_id, "handle_request_entered", request_len=len(request_text))
        log_online_timepoint(logger, trace_id, "parse_request_start")
    parsed = parse_request(request_text)
    if logger is not None:
        logger.info("request received: type=%s arg=%s", parsed.req_type, parsed.arg)
    if parsed.req_type == "ONLINE":
        log_online_timepoint(logger, trace_id, "parse_request_completed", arg=parsed.arg)
        log_online_timepoint(logger, trace_id, "password_check_start")

    if parsed.param != PASSWORD:
        if logger is not None:
            logger.warning("request rejected: invalid password for type=%s", parsed.req_type)
        if parsed.req_type == "ONLINE":
            log_online_timepoint(logger, trace_id, "password_check_failed")
            log_online_timepoint(logger, trace_id, "json_encode_start", response_kind="invalid_password")
            response = json_response({"success": False, "info": "invalid_password"})
            log_online_timepoint(logger, trace_id, "json_encode_completed", response_len=len(response))
            return response
        return json_response({"success": False, "info": "invalid_password"})

    if parsed.req_type == "ONLINE":
        log_online_timepoint(logger, trace_id, "password_check_passed")
        log_online_timepoint(logger, trace_id, "provider_fetch_start")
        raw_data = provider_fetcher()
        log_online_timepoint(logger, trace_id, "provider_fetch_completed", provider_type=type(raw_data).__name__)
        log_online_timepoint(logger, trace_id, "convert_provider_start")
        converted_data = convert_provider_data(raw_data)
        log_online_timepoint(logger, trace_id, "convert_provider_completed")
        log_online_diagnostics(logger, raw_data, converted_data, trace_id=trace_id)
        log_online_timepoint(logger, trace_id, "json_encode_start", response_kind="online_success")
        response = json_response(converted_data)
        if logger is not None:
            logger.info("ONLINE response JSON: %s", response)
        log_online_timepoint(logger, trace_id, "json_encode_completed", response_len=len(response))
        return response

    if parsed.req_type == "OFFLINE":
        if offline_handler is None:
            return json_response({"success": False, "info": "offline_not_configured"})
        return json_response(offline_handler(parsed.arg))

    if parsed.req_type == "SHUTDOWN":
        if shutdown_handler is None:
            return json_response({"success": False, "info": "shutdown_not_configured"})
        if logger is not None:
            logger.info("shutdown requested by authenticated client")
        shutdown_handler()
        return json_response({"success": True, "info": "shutdown_requested"})

    return json_response(
        {"success": False, "info": "unknown_request_type", "req_type": parsed.req_type}
    )


def scan_json_end(text: str, start_idx: int = 0) -> int:
    i = start_idx
    n = len(text)
    while i < n and text[i].isspace():
        i += 1
    if i >= n or text[i] not in "{[":
        return -1

    stack = [text[i]]
    i += 1
    in_str = False
    esc = False
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                opener = stack.pop()
                if (opener == "{" and ch != "}") or (opener == "[" and ch != "]"):
                    return -1
                if not stack:
                    return i + 1
        i += 1
    return -1


def try_parse_buffer(buffer: str) -> Optional[Tuple[str, str]]:
    stripped = buffer.lstrip("\r\n")
    offset = len(buffer) - len(stripped)
    first = stripped.find(";")
    if first < 0:
        return None
    second = stripped.find(";", first + 1)
    if second < 0:
        return None

    rest = stripped[second + 1 :]
    json_end = scan_json_end(rest)
    if json_end >= 0:
        request_text = stripped[: second + 1 + json_end]
        remaining = stripped[second + 1 + json_end :].lstrip("\r\n")
        return request_text, remaining

    if "\n" in stripped:
        line, remaining = stripped.split("\n", 1)
        return line.strip(), remaining

    if offset:
        return None
    return None


class ApiServer:
    def __init__(self, provider: PyMobileCommProvider, logger: logging.Logger, offline_manager: OfflineSessionManager):
        self._provider = provider
        self._logger = logger
        self._offline_manager = offline_manager
        self._stop_event = threading.Event()
        self._server_socket: Optional[socket.socket] = None

    def request_shutdown(self) -> None:
        self._stop_event.set()
        if self._server_socket is not None:
            try:
                self._server_socket.close()
            except OSError:
                pass
            finally:
                self._server_socket = None

    def handle_client(self, client_socket: socket.socket, client_address) -> None:
        self._logger.info("client connected: %s", client_address)
        buffer = ""
        try:
            while True:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="strict")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        self._send_response(client_socket, line)

                while True:
                    parsed = try_parse_buffer(buffer)
                    if parsed is None:
                        break
                    request_text, buffer = parsed
                    self._send_response(client_socket, request_text)
        finally:
            client_socket.close()
            self._logger.info("client closed: %s", client_address)

    def _send_response(self, client_socket: socket.socket, request_text: str) -> None:
        trace_id = None
        is_online_request = request_type_hint(request_text) == "ONLINE"
        if is_online_request:
            trace_id = f"{threading.get_ident()}-{time.time_ns()}"
            log_online_timepoint(
                self._logger,
                trace_id,
                "socket_request_dispatch_start",
                request_len=len(request_text),
            )
        try:
            response = handle_request(
                request_text,
                (lambda: self._provider.fetch_online(trace_id=trace_id))
                if is_online_request
                else self._provider.fetch,
                logger=self._logger,
                offline_handler=self._offline_manager.handle,
                shutdown_handler=self.request_shutdown,
                trace_id=trace_id,
            )
        except Exception as exc:
            self._logger.exception("request failed: %r", request_text)
            if is_online_request:
                log_online_timepoint(
                    self._logger,
                    trace_id,
                    "request_exception_caught",
                    error=repr(exc),
                )
                log_online_timepoint(
                    self._logger,
                    trace_id,
                    "json_encode_start",
                    response_kind="request_failed",
                )
            response = json_response({"success": False, "info": "request_failed", "error": str(exc)})
            if is_online_request:
                log_online_timepoint(self._logger, trace_id, "json_encode_completed", response_len=len(response))
        if is_online_request:
            log_online_timepoint(self._logger, trace_id, "socket_send_start", response_len=len(response))
        self._logger.info("response sent: %s", response)
        client_socket.sendall((response + "\n").encode("utf-8"))
        if is_online_request:
            log_online_timepoint(self._logger, trace_id, "socket_send_completed", response_len=len(response))

    def serve_forever(self, host: str, port: int) -> None:
        self._stop_event.clear()
        with build_server_socket(host, port, logger=self._logger) as server_socket:
            self._server_socket = server_socket
            server_socket.listen(5)
            server_socket.settimeout(0.5)
            self._logger.info("api server listening on %s:%s", host, port)
            print(f"api server listening on {host}:{port}", flush=True)

            try:
                while not self._stop_event.is_set():
                    try:
                        client_socket, client_address = server_socket.accept()
                    except socket.timeout:
                        continue
                    except OSError:
                        if self._stop_event.is_set():
                            break
                        raise
                    threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_address),
                        daemon=True,
                    ).start()
            finally:
                self._server_socket = None
                self._logger.info("api server stopped listening on %s:%s", host, port)


def build_logger() -> logging.Logger:
    if getattr(sys, "frozen", False):
        log_dir = Path(sys.executable).resolve().parent / "ocrlog"
    else:
        log_dir = Path(__file__).resolve().parents[2] / "ocrlog"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pywrapper_api_server")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_dir / "pywrapper_api_server.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
    logger.info("log file: %s", log_dir / "pywrapper_api_server.log")
    return logger


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PyMobileComm TCP API server")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    logger = build_logger()
    log_process_environment(logger)
    offline_config = load_offline_config(logger)
    provider = PyMobileCommProvider(logger)
    offline_manager = OfflineSessionManager(
        provider_fetcher=provider.fetch,
        frame_fetcher=provider.get_latest_frame,
        config=offline_config,
        logger=logger,
    )
    try:
        ApiServer(provider, logger, offline_manager).serve_forever(args.host, args.port)
    finally:
        provider.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
