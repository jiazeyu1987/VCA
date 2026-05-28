# -*- coding: utf-8 -*-
import argparse
import ctypes
import errno
import json
import logging
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
FOCUS_MARKER_COLOR = (128, 0, 128)
DIFFER_MARKER_WIDTH = 3
FOCUS_MARKER_RADIUS = 3


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
    difference_threshold: float = 0.5
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


@dataclass
class OfflineSession:
    point_id: object
    duration_s: float
    is_save: bool
    stop_event: threading.Event
    capture_done_event: threading.Event = field(default_factory=threading.Event)
    finished_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
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
    roi2_rect: Optional[Tuple[int, int, int, int]] = None
    roi3_rect: Optional[Tuple[int, int, int, int]] = None
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
    final_roi2_color: str = "red"
    response: dict = field(default_factory=dict)
    frame_buffer: list[OfflineFrameRecord] = field(default_factory=list)
    debug_dir: Optional[str] = None
    meta: dict = field(default_factory=dict)


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


def write_png(path: Path, image: np.ndarray) -> None:
    arr = np.asarray(image)
    if arr.ndim == 2:
        pil_image = Image.fromarray(arr)
    elif arr.ndim == 3 and arr.shape[2] == 3:
        pil_image = Image.fromarray(arr.astype(np.uint8))
    elif arr.ndim == 3 and arr.shape[2] == 4:
        pil_image = Image.fromarray(arr.astype(np.uint8))
    else:
        raise ValueError(f"unsupported image shape for png: {arr.shape}")
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
    width, height = image_size
    x, y = [int(v) for v in focus_anchor]
    if x < 0 or y < 0 or x >= width or y >= height:
        raise ValueError(f"focus marker outside image bounds focus={focus_anchor} size={image_size}")
    radius = FOCUS_MARKER_RADIUS
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=FOCUS_MARKER_COLOR)


def draw_differ_roi_markers(
    draw: ImageDraw.ImageDraw,
    image_size: Tuple[int, int],
    session: "OfflineSession",
) -> None:
    width, height = image_size
    draw_marker_rect(draw, image_size, (0, 0, width, height), ROI1_MARKER_COLOR)
    if session.roi2_rect is not None:
        draw_marker_rect(draw, image_size, session.roi2_rect, ROI2_MARKER_COLOR)
    if session.roi3_rect is not None:
        draw_marker_rect(draw, image_size, session.roi3_rect, ROI3_MARKER_COLOR)
    if session.focus_anchor is not None:
        draw_focus_marker(draw, image_size, session.focus_anchor)


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


def update_segment_images_info(db_root_dir: Optional[str], point_id, before_path: str, after_path: str) -> None:
    if not db_root_dir:
        return
    db_root = Path(db_root_dir)
    db_paths = [db_root / "ccwssm", db_root / "zccwssm"]
    modify_time = datetime.now().strftime("%Y_%m_%d-%H_%M_%S_%f")[:-3]
    image_path = before_path + ";" + after_path + ";" + after_path.replace("_after", "_diff")
    sql = """
        UPDATE SegmentImagesInfo
        SET ImagePath = ?, ModifyTime = ?
        WHERE ID = ?
    """
    for db_path in db_paths:
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        try:
            cur = conn.cursor()
            cur.execute(sql, (image_path, modify_time, point_id))
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
    ]
    line_ok = [
        roi2_ok,
        roi2_ok,
        bool(session.roi3_override_method == "roi3_g1_g2"),
        bool(session.roi3_override_method == "roi3_column_diff"),
    ]
    return lines, line_ok


def render_diff_with_overlay(session: "OfflineSession", config: OfflineConfig) -> Optional[np.ndarray]:
    if session.before is None or session.after is None:
        return None
    diff = positive_diff_image(session.before, session.after)
    rgb = np.asarray(diff, dtype=np.uint8)
    if rgb.ndim == 2:
        rgb = np.stack([rgb, rgb, rgb], axis=2)
    image = Image.fromarray(rgb)
    draw = ImageDraw.Draw(image)
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
    draw_differ_roi_markers(draw, image.size, session)
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
    image_output_dir = settings.get("image_output_dir", "D:/software_data/imgs")
    db_root_dir = settings.get("db_root_dir", "D:/software_data")
    result_flag_path = settings.get("result_flag_path", "D:/software_data/result.txt")

    config = OfflineConfig(
        screenshot_test_enabled=bool(screenshot_cfg.get("enabled", False)),
        screenshot_capture_bbox=screenshot_capture_bbox,
        peak_detect_enabled=True,
        roi2_extension_params=dict(roi2_ext),
        roi3_extension_params=dict(roi3_ext),
        difference_threshold=float(threshold),
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
    )
    logger.info(
        "offline config loaded: screenshot_test_enabled=%s screenshot_capture_bbox=%s peak_detect_enabled=%s offline_peak_enabled=%s offline_peak_threshold=%s "
        "roi2_extension_params=%s roi3_extension_params=%s difference_threshold=%s debug_save_enabled=%s "
        "debug_save_dir=%s stop_wait_timeout_seconds=%s image_output_dir=%s db_root_dir=%s result_flag_path=%s",
        config.screenshot_test_enabled,
        config.screenshot_capture_bbox,
        config.peak_detect_enabled,
        config.offline_peak_enabled,
        config.offline_peak_threshold,
        config.roi2_extension_params,
        config.roi3_extension_params,
        config.difference_threshold,
        config.debug_save_enabled,
        config.debug_save_dir,
        config.stop_wait_timeout_seconds,
        config.image_output_dir,
        config.db_root_dir,
        config.result_flag_path,
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

    def _initialize_focus_and_rois(self, session: OfflineSession, before_frame: np.ndarray) -> None:
        raw_provider = self._provider_fetcher()
        focus_point = raw_provider.get("focus_point") if isinstance(raw_provider, dict) else None
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
            session.roi2_rect = roi2_rect
            session.roi3_rect = roi3_rect
            self._set_cached_roi_state(anchor, roi2_rect, roi3_rect)
        session.meta["provider_focus_point"] = focus_point
        self._offline_diag(
            "focus_roi_initialized",
            point_id=session.point_id,
            capture_source="image_matrix",
            provider_focus_point=focus_point,
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
            if (not before_written) and record.tag == "before":
                write_jsonl_line(
                    meta_jsonl,
                    {
                        "event": "before_saved",
                        "filename": name,
                        "point_id": session.point_id,
                        "frame_index": record.frame_index,
                        "ts": format_frame_timestamp(record.ts),
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
        meta["roi2_rect"] = [int(v) for v in session.roi2_rect] if session.roi2_rect is not None else None
        meta["roi3_rect"] = [int(v) for v in session.roi3_rect] if session.roi3_rect is not None else None
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
        }
        self._debug_saver.write_meta(session.debug_dir, meta)

    def _save_final_outputs(self, session: OfflineSession) -> dict:
        if not self._config.image_output_dir:
            return {}
        img_dir = Path(self._config.image_output_dir)
        img_dir.mkdir(parents=True, exist_ok=True)
        before_path = img_dir / f"{session.before_name or 'before'}_before.png"
        after_path = img_dir / f"{session.after_name or 'after'}_after.png"
        if not session.is_save:
            before_path = img_dir / "energy_before.png"
            after_path = img_dir / "energy_after.png"
        if session.before is not None:
            write_png(before_path, session.before)
        if session.after is not None:
            write_png(after_path, session.after)
        result = {}
        if session.before is not None:
            result["before_path"] = str(before_path)
        if session.after is not None:
            result["after_path"] = str(after_path)
        if session.before is not None and session.after is not None:
            diff_path = Path(str(after_path).replace("_after", "_diff"))
            diff_with_overlay = render_diff_with_overlay(session, self._config)
            if diff_with_overlay is not None:
                write_png(diff_path, diff_with_overlay)
            result["diff_path"] = str(diff_path)
            try:
                write_result_flag(self._config.result_flag_path, session.final_roi2_color == "green")
                self._offline_diag(
                    "result_flag_written",
                    point_id=session.point_id,
                    capture_source="image_matrix",
                    result_flag_path=self._config.result_flag_path,
                    value="1" if session.final_roi2_color == "green" else "0",
                )
            except Exception:
                self._logger.exception("OFFLINE result flag write failed: point_id=%s", session.point_id)
            if session.is_save:
                try:
                    update_segment_images_info(self._config.db_root_dir, session.point_id, str(before_path), str(after_path))
                    self._offline_diag(
                        "db_update_completed",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        before_path=str(before_path),
                        after_path=str(after_path),
                        db_root_dir=self._config.db_root_dir,
                    )
                except Exception:
                    self._logger.exception("OFFLINE db update failed: point_id=%s", session.point_id)
        self._offline_diag(
            "final_outputs_saved",
            point_id=session.point_id,
            capture_source="image_matrix",
            is_save=bool(session.is_save),
            output_dir=str(img_dir),
            before_path=result.get("before_path"),
            after_path=result.get("after_path"),
            diff_path=result.get("diff_path"),
        )
        return result

    def _run_session(self, session: OfflineSession) -> None:
        timed_out = False
        last_seq = None
        frame_index = 0
        before_default = None
        before_default_seq = None
        before_default_ts = None
        before_gray_mean = None
        peak_threshold = None
        peak_in_high = False
        peak_in_descent = False
        peak_found = False
        after_target_frame = None
        prev_is_high = None
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
            offline_peak_after_delay_frames=int(self._config.offline_peak_after_delay_frames),
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
                if before_default is None:
                    before_default = frame_image
                    before_default_seq = frame.seq
                    before_default_ts = frame.ts
                if session.before is None:
                    session.before = frame_image
                    session.before_seq = frame.seq
                    session.before_ts = frame.ts
                    session.before_name = format_frame_timestamp(frame.ts)
                    before_gray_mean = float(roi1_gray)
                    self._initialize_focus_and_rois(session, frame_image)
                    if session.roi2_rect is not None:
                        session.before_mean = roi_gray_mean(frame_image, session.roi2_rect)
                    if self._config.offline_peak_enabled and self._config.offline_peak_threshold is not None:
                        peak_threshold = float(before_gray_mean) + float(self._config.offline_peak_threshold)
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
                    if peak_threshold is not None:
                        self._offline_diag(
                            "peak_threshold_initialized",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            before_gray_mean=round(float(before_gray_mean), 6),
                            peak_threshold=round(float(peak_threshold), 6),
                            threshold_offset=round(float(self._config.offline_peak_threshold), 6) if self._config.offline_peak_threshold is not None else None,
                        )
                self._append_frame_buffer(session, frame_image, frame.seq, frame.ts, frame_index, "before" if frame_index == 1 else "frame", roi1_gray)
                if not self._config.offline_peak_enabled or before_gray_mean is None:
                    time.sleep(0.01)
                    continue
                if peak_threshold is None:
                    peak_threshold = float(before_gray_mean) + float(self._config.offline_peak_threshold or 0.0)
                is_high = float(roi1_gray) >= float(peak_threshold)
                if prev_is_high is None:
                    prev_is_high = is_high
                    time.sleep(0.01)
                    continue
                if (not peak_found) and (not peak_in_high) and (not peak_in_descent) and (not prev_is_high) and is_high:
                    peak_in_high = True
                    self._offline_diag(
                        "peak_enter_high",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(frame_index),
                        frame_seq=int(frame.seq),
                        roi1_gray=round(float(roi1_gray), 6),
                        peak_threshold=round(float(peak_threshold), 6),
                    )
                if (not peak_found) and peak_in_high and prev_is_high and (not is_high):
                    peak_in_high = False
                    peak_in_descent = True
                    self._offline_diag(
                        "peak_descent_started",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(frame_index),
                        frame_seq=int(frame.seq),
                        roi1_gray=round(float(roi1_gray), 6),
                    )
                if (not peak_found) and peak_in_descent and before_gray_mean is not None:
                    if abs(float(roi1_gray) - float(before_gray_mean)) <= float(self._config.offline_peak_end_diff_threshold):
                        peak_in_descent = False
                        peak_found = True
                        after_target_frame = frame_index + max(0, int(self._config.offline_peak_after_delay_frames))
                        self._offline_diag(
                            "peak_end_detected",
                            point_id=session.point_id,
                            capture_source="image_matrix",
                            frame_index=int(frame_index),
                            frame_seq=int(frame.seq),
                            roi1_gray=round(float(roi1_gray), 6),
                            before_gray_mean=round(float(before_gray_mean), 6),
                            after_target_frame=int(after_target_frame),
                            end_diff_threshold=round(float(self._config.offline_peak_end_diff_threshold), 6),
                        )
                if peak_found and session.after is None and after_target_frame is not None and frame_index == after_target_frame:
                    session.after = frame_image
                    session.after_seq = frame.seq
                    session.after_ts = frame.ts
                    session.after_name = format_frame_timestamp(frame.ts)
                    session.after_method = f"peak+{int(self._config.offline_peak_after_delay_frames)}"
                    self._append_frame_buffer(session, frame_image, frame.seq, frame.ts, frame_index, "after_peak", roi1_gray)
                    self._offline_diag(
                        "after_selected",
                        point_id=session.point_id,
                        capture_source="image_matrix",
                        frame_index=int(frame_index),
                        frame_seq=int(frame.seq),
                        frame_ts=round(float(frame.ts), 6),
                        after_name=session.after_name,
                        after_method=session.after_method,
                        roi1_gray=round(float(roi1_gray), 6),
                    )
                prev_is_high = is_high
                time.sleep(0.01)
        except Exception as exc:
            self._logger.exception("OFFLINE session worker failed: point_id=%s", session.point_id)
            session.response = {"success": False, "info": "error_in_detect", "point_id": session.point_id, "error": str(exc)}
        finally:
            session.capture_done_event.set()
            if session.before is None and before_default is not None:
                session.before = before_default
                session.before_seq = before_default_seq
                session.before_ts = before_default_ts
                session.before_name = format_frame_timestamp(before_default_ts) if before_default_ts is not None else ""
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
                    self._apply_roi3_overrides(session)

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
                frame_shape=[int(v) for v in session.after.shape] if session.after is not None else None,
            )

            try:
                result_paths = self._save_final_outputs(session)
            except Exception:
                self._logger.exception("OFFLINE final output save failed: point_id=%s", session.point_id)
                result_paths = {}
            try:
                self._save_debug_outputs(session)
            except Exception:
                self._logger.exception("OFFLINE debug save failed on finish: point_id=%s", session.point_id)
                session.response = {
                    "success": False,
                    "info": "debug_save_failed",
                    "point_id": session.point_id,
                }
                session.finished_event.set()
                return

            session.response = {
                "success": True,
                "info": "offline_stop_completed",
                "point_id": session.point_id,
                "peak_detect_enabled": bool(self._config.peak_detect_enabled),
                "roi2_color": session.final_roi2_color,
                "roi2_diff": round(float(session.roi2_diff), 6) if session.roi2_diff is not None else None,
                "roi2_before_mean": round(float(session.before_mean), 6) if session.before_mean is not None else None,
                "roi2_after_mean": round(float(session.after_mean), 6) if session.after_mean is not None else None,
                "focus_anchor": [int(session.focus_anchor[0]), int(session.focus_anchor[1])] if session.focus_anchor is not None else None,
                "roi2_rect": [int(v) for v in session.roi2_rect] if session.roi2_rect is not None else None,
                "roi3_rect": [int(v) for v in session.roi3_rect] if session.roi3_rect is not None else None,
                "after_method": session.after_method,
                "roi3_g1": session.roi3_g1,
                "roi3_g2": session.roi3_g2,
                "roi3_column_diff": session.roi3_column_diff,
                "roi3_override_applied": session.roi3_override_applied,
                "roi3_override_method": session.roi3_override_method,
                "roi3_override_frame_index": session.roi3_override_frame_index,
                "roi3_override_tag": session.roi3_override_tag,
            }
            session.response.update(result_paths)
            if session.debug_dir is not None:
                session.response["debug_dir"] = session.debug_dir
            session.finished_event.set()


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
