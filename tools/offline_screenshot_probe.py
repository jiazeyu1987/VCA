from __future__ import annotations

import argparse
import importlib.util
import itertools
import json
import logging
import math
from dataclasses import replace
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, NamedTuple, Optional

import numpy as np


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 30415
DEFAULT_PASSWORD = "31415"
SCREENSHOT_WIRING_TOKENS = (
    "offline_screenshot_test",
    "pyautogui",
    "screenshot(",
    "get_screen_shot",
    "ImageGrab",
    "mss",
)
SCREENSHOT_EVIDENCE_PATTERNS = (
    "screenshot region",
    "screenshot capture",
    "stop-time screenshot",
    "final screenshot",
    "pyautogui",
    '"capture_source": "screenshot"',
)


class OnlineProbeRecord(NamedTuple):
    window_index: int
    start_ts: float
    end_ts: float
    latency_ms: Optional[float]
    parsed: bool
    timed_out: bool
    empty_fields: list[str]


class FixedRawProvider:
    def __init__(self, raw_payload: dict[str, Any]):
        self._raw_payload = dict(raw_payload)

    def fetch_online(self, trace_id: Optional[str] = None) -> dict[str, Any]:
        return dict(self._raw_payload)

    def fetch(self) -> dict[str, Any]:
        return dict(self._raw_payload)

    def close(self) -> None:
        return


class FixedFrameSource:
    def __init__(self, api_server_module, width: int = 64, height: int = 64):
        self._module = api_server_module
        self._counter = itertools.count(1)
        self._width = width
        self._height = height
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            seq = next(self._counter)
        value = 32 if seq % 2 else 48
        frame = np.full((self._height, self._width, 3), value, dtype=np.uint8)
        return self._module.FrameSnapshot(frame, seq, time.time())


def build_request_text(req_type: str, password: str, payload: Optional[dict[str, Any]]) -> str:
    request_type = req_type.strip().upper()
    if not request_type:
        raise ValueError("request type is empty")
    password_text = password.strip()
    if not password_text:
        raise ValueError("password is empty")
    if payload is None:
        return f"{request_type};{password_text}\n"
    return f"{request_type};{password_text};{json.dumps(payload, ensure_ascii=False)}\n"


def send_tcp_request(
    host: str,
    port: int,
    req_type: str,
    password: str,
    payload: Optional[dict[str, Any]],
    timeout_s: float,
) -> tuple[Optional[dict[str, Any]], str, bool]:
    request_text = build_request_text(req_type, password, payload)
    with socket.create_connection((host, port), timeout=timeout_s) as client:
        client.settimeout(timeout_s)
        client.sendall(request_text.encode("utf-8"))
        chunks: list[bytes] = []
        recv_timed_out = False
        while True:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                recv_timed_out = True
                break
            if not chunk:
                break
            chunks.append(chunk)
            if b"\n" in chunk:
                break
    raw = b"".join(chunks).decode("utf-8", errors="replace").splitlines()
    response_text = raw[0].strip() if raw else ""
    if not response_text:
        return None, response_text, recv_timed_out
    try:
        return json.loads(response_text), response_text, recv_timed_out
    except Exception:
        return None, response_text, recv_timed_out


def scan_screenshot_runtime_wiring(api_server_path: Path) -> dict[str, Any]:
    text = api_server_path.read_text(encoding="utf-8", errors="ignore")
    matched_tokens = [token for token in SCREENSHOT_WIRING_TOKENS if token in text]
    return {
        "api_server_path": str(api_server_path),
        "screenshot_flag_wired": bool(matched_tokens),
        "matched_tokens": matched_tokens,
    }


def build_default_fixed_provider_data() -> dict[str, Any]:
    return {
        "focus_depth": "7.5",
        "guankuan_a": "10.1",
        "guankuan_b": "20.2",
        "depth": "35",
        "focus_point": "PointF(320, 240)",
        "isLive": True,
        "mode": 1,
        "Alpha": "0",
    }


def build_probe_settings(base_settings: dict[str, Any], output_root: Path) -> dict[str, Any]:
    settings = json.loads(json.dumps(base_settings))
    settings.setdefault("offline_screenshot_test", {})
    if not isinstance(settings["offline_screenshot_test"], dict):
        settings["offline_screenshot_test"] = {}
    settings["offline_screenshot_test"]["enabled"] = True

    settings.setdefault("offline_tmp_frames", {})
    if not isinstance(settings["offline_tmp_frames"], dict):
        settings["offline_tmp_frames"] = {}
    settings["offline_tmp_frames"]["dir"] = (output_root / "offline_tmp_frames").as_posix()

    settings["image_output_dir"] = (output_root / "image_output").as_posix()
    settings["result_flag_path"] = (output_root / "result_flag.txt").as_posix()
    settings["db_root_dir"] = None
    return settings


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare_runtime_copy(workspace_root: Path, run_root: Path) -> dict[str, Path]:
    packaged_runtime = workspace_root / "dist" / "OCRSERVER"
    if not packaged_runtime.exists():
        raise FileNotFoundError(f"packaged runtime not found: {packaged_runtime}")

    runtime_root = run_root / "OCRSERVER"
    if runtime_root.exists():
        raise FileExistsError(f"runtime copy target already exists: {runtime_root}")
    shutil.copytree(packaged_runtime, runtime_root)

    base_settings_path = workspace_root / "settings"
    if not base_settings_path.exists():
        raise FileNotFoundError(f"settings file not found: {base_settings_path}")
    base_settings = json.loads(base_settings_path.read_text(encoding="utf-8"))

    probe_output_root = run_root / "probe_outputs"
    updated_settings = build_probe_settings(base_settings, probe_output_root)
    runtime_settings_path = runtime_root / "settings"
    write_json_file(runtime_settings_path, updated_settings)
    return {
        "runtime_root": runtime_root,
        "runtime_settings_path": runtime_settings_path,
        "probe_output_root": probe_output_root,
        "probe_settings": updated_settings,
    }


def prepare_no_device_runtime(workspace_root: Path, run_root: Path) -> dict[str, Path]:
    base_settings_path = workspace_root / "settings"
    if not base_settings_path.exists():
        raise FileNotFoundError(f"settings file not found: {base_settings_path}")
    base_settings = json.loads(base_settings_path.read_text(encoding="utf-8"))

    runtime_root = run_root / "mock_runtime"
    runtime_root.mkdir(parents=True, exist_ok=False)
    probe_output_root = run_root / "probe_outputs"
    updated_settings = build_probe_settings(base_settings, probe_output_root)
    runtime_settings_path = runtime_root / "settings"
    write_json_file(runtime_settings_path, updated_settings)
    return {
        "runtime_root": runtime_root,
        "runtime_settings_path": runtime_settings_path,
        "probe_output_root": probe_output_root,
        "probe_settings": updated_settings,
    }


def load_api_server_module(workspace_root: Path):
    module_path = workspace_root / "resource" / "pywrapper" / "api_server.py"
    spec = importlib.util.spec_from_file_location("offline_screenshot_probe_api_server", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_probe_logger(log_dir: Path, logger_name: str) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_dir / "pywrapper_api_server.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    return logger


def collect_file_inventory(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }


def classify_runtime_evidence(log_text: str, created_files: list[str]) -> dict[str, Any]:
    capture_sources = sorted(
        {
            fragment.split('"capture_source": "', 1)[1].split('"', 1)[0]
            for fragment in log_text.splitlines()
            if '"capture_source": "' in fragment
        }
    )
    screenshot_log_hits = [
        line for line in log_text.splitlines()
        if any(pattern in line.lower() for pattern in SCREENSHOT_EVIDENCE_PATTERNS)
    ]
    screenshot_file_hits = [
        path for path in created_files
        if "screenshot" in path.lower()
    ]
    return {
        "capture_sources_seen": capture_sources,
        "screenshot_event_count": len(screenshot_log_hits) + len(screenshot_file_hits),
        "screenshot_log_hits": screenshot_log_hits,
        "screenshot_file_hits": screenshot_file_hits,
    }


def summarize_online_records(records: list[OnlineProbeRecord], expected_window_count: int) -> dict[str, Any]:
    parsed_records = [record for record in records if record.parsed]
    latencies = [record.latency_ms for record in parsed_records if record.latency_ms is not None]
    successful_windows = {record.window_index for record in parsed_records}
    missed_windows = [
        index for index in range(max(0, expected_window_count))
        if index not in successful_windows
    ]
    online_empty_field_count = sum(1 for record in parsed_records if record.empty_fields)
    latency_summary = {"min": None, "max": None, "avg": None, "p95": None}
    if latencies:
        ordered = sorted(latencies)
        p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
        latency_summary = {
            "min": min(ordered),
            "max": max(ordered),
            "avg": round(statistics.mean(ordered), 3),
            "p95": ordered[p95_index],
        }
    return {
        "online_probe_count": len(records),
        "online_success_count": len(parsed_records),
        "online_timeout_count": sum(1 for record in records if record.timed_out),
        "online_empty_field_count": online_empty_field_count,
        "online_missed_second_windows": missed_windows,
        "online_latency_ms": latency_summary,
    }


def build_final_conclusion(report: dict[str, Any]) -> str:
    lines = []
    if (
        report.get("screenshot_event_count") == 0
        and "image_matrix" in report.get("capture_sources_seen", [])
    ):
        lines.append("当前 D:\\ocr3 构建未观察到 screenshot 路径。")
        lines.append("offline_screenshot_test.enabled=true 对当前 pywrapper OFFLINE 无显式运行效果。")
    elif report.get("screenshot_event_count", 0) > 0:
        lines.append("当前运行观测到了 screenshot 专属证据。")
    else:
        lines.append("本次运行未收集到足够证据证明存在 screenshot 路径。")

    missed = report.get("online_missed_second_windows", [])
    if not missed and report.get("online_success_count", 0) > 0:
        lines.append("ONLINE 每秒至少收到一次可解析响应。")
    elif missed:
        lines.append(f"ONLINE 存在丢秒窗口: {missed}")
    else:
        lines.append("ONLINE 未达到每秒至少一次可解析响应。")

    if not report.get("screenshot_flag_wired", False):
        lines.append("静态检查显示当前 pywrapper 源码未接入 screenshot 运行时分支。")
    return "\n".join(lines)


def write_report_files(output_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "offline_screenshot_probe_report.json"
    summary_path = output_dir / "offline_screenshot_probe_summary.txt"
    write_json_file(json_path, report)
    summary_lines = [f"{key}: {value}" for key, value in report.items()]
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    return {
        "json_report": str(json_path),
        "summary_report": str(summary_path),
    }


def read_log_excerpt(log_path: Path) -> tuple[str, list[str]]:
    if not log_path.exists():
        return "", []
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    relevant = [
        line for line in text.splitlines()
        if "OFFLINE diag" in line or "ONLINE timepoint" in line or "screenshot" in line.lower()
    ]
    return text, relevant[-120:]


def collect_probe_runtime_inventory(run_root: Path, runtime_root: Path, probe_output_root: Path) -> set[str]:
    result: set[str] = set()
    if runtime_root.exists():
        result.update(
            path.relative_to(run_root).as_posix()
            for path in runtime_root.rglob("*")
            if path.is_file()
        )
    if probe_output_root.exists():
        result.update(
            path.relative_to(run_root).as_posix()
            for path in probe_output_root.rglob("*")
            if path.is_file()
        )
    return result


def build_final_conclusion(report: dict[str, Any]) -> str:
    lines = []
    if (
        report.get("screenshot_event_count") == 0
        and "image_matrix" in report.get("capture_sources_seen", [])
    ):
        lines.append("Current D:\\ocr3 build did not observe a screenshot path.")
        lines.append("offline_screenshot_test.enabled=true had no explicit effect on the current pywrapper OFFLINE path.")
    elif report.get("screenshot_event_count", 0) > 0:
        lines.append("Current run observed screenshot-specific evidence.")
    else:
        lines.append("This run did not collect enough evidence to prove a screenshot path.")

    missed = report.get("online_missed_second_windows", [])
    if not missed and report.get("online_success_count", 0) > 0:
        lines.append("ONLINE delivered at least one parseable response per second.")
    elif missed:
        lines.append(f"ONLINE missed second windows: {missed}")
    else:
        lines.append("ONLINE did not achieve one parseable response per second.")

    if not report.get("screenshot_flag_wired", False):
        lines.append("Static inspection shows the current pywrapper source has not wired in a screenshot runtime branch.")
    return "\n".join(lines)


def ensure_port_available(host: str, port: int, timeout_s: float) -> None:
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            probe_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            probe_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe_socket.bind((host, port))
    except OSError as exc:
        raise RuntimeError(f"precondition failed: {host}:{port} is already occupied or unavailable: {exc}") from exc
    finally:
        probe_socket.close()


def wait_for_server_ready(host: str, port: int, timeout_s: float, poll_interval_s: float = 0.5) -> None:
    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            payload, _, _ = send_tcp_request(host, port, "ONLINE", "bad", {}, timeout_s=min(1.0, poll_interval_s))
            if isinstance(payload, dict) and payload.get("info") == "invalid_password":
                return
        except Exception as exc:
            last_error = exc
        time.sleep(poll_interval_s)
    raise RuntimeError(f"server did not become ready on {host}:{port}: {last_error}")


def wait_for_server_port_closed(host: str, port: int, timeout_s: float, poll_interval_s: float = 0.5) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=min(poll_interval_s, 1.0)):
                time.sleep(poll_interval_s)
                continue
        except ConnectionRefusedError:
            return
        except OSError:
            return
    raise RuntimeError(f"server port {host}:{port} did not close within {timeout_s} seconds")


def probe_online_once(host: str, port: int, password: str, timeout_s: float, base_ts: float, interval_s: float) -> OnlineProbeRecord:
    start_ts = time.time()
    window_index = int((start_ts - base_ts) / interval_s) if interval_s > 0 else 0
    timed_out = False
    parsed = False
    payload = None
    try:
        payload, _, recv_timed_out = send_tcp_request(host, port, "ONLINE", password, {}, timeout_s=timeout_s)
        parsed = isinstance(payload, dict)
        timed_out = bool(recv_timed_out and not parsed)
    except socket.timeout:
        timed_out = True
    except TimeoutError:
        timed_out = True
    except Exception:
        parsed = False
        timed_out = False
    end_ts = time.time()
    empty_fields: list[str] = []
    if isinstance(payload, dict):
        empty_fields = [
            key for key, value in payload.items()
            if value in (None, "")
        ]
    latency_ms = round((end_ts - start_ts) * 1000.0, 3) if parsed else None
    return OnlineProbeRecord(
        window_index=window_index,
        start_ts=start_ts,
        end_ts=end_ts,
        latency_ms=latency_ms,
        parsed=parsed,
        timed_out=timed_out,
        empty_fields=empty_fields,
    )


def run_online_probe_loop(
    host: str,
    port: int,
    password: str,
    timeout_s: float,
    interval_s: float,
    stop_event: threading.Event,
    records: list[OnlineProbeRecord],
    base_ts: float,
) -> None:
    while not stop_event.is_set():
        records.append(probe_online_once(host, port, password, timeout_s, base_ts, interval_s))
        if stop_event.wait(interval_s):
            break


def launch_server_process(exe_path: Path) -> subprocess.Popen:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [str(exe_path)],
        cwd=str(exe_path.parent),
        creationflags=creationflags,
    )


def launch_no_device_server(
    workspace_root: Path,
    runtime_info: dict[str, Any],
    host: str,
    port: int,
    fixed_provider_payload: dict[str, Any],
) -> tuple[threading.Thread, FixedRawProvider, Any]:
    api_server_module = load_api_server_module(workspace_root)
    logger = build_probe_logger(
        runtime_info["runtime_root"] / "ocrlog",
        logger_name=f"offline_screenshot_probe_mock_{time.time_ns()}",
    )
    logger.info("starting no-device fixed-data runtime mode")
    config = api_server_module.parse_offline_config(runtime_info["probe_settings"], logger)
    config = replace(
        config,
        image_output_dir=(runtime_info["probe_output_root"] / "image_output").as_posix(),
        db_root_dir=None,
        result_flag_path=(runtime_info["probe_output_root"] / "result_flag.txt").as_posix(),
    )
    provider = FixedRawProvider(fixed_provider_payload)
    frame_source = FixedFrameSource(api_server_module)
    offline_manager = api_server_module.OfflineSessionManager(
        provider_fetcher=provider.fetch,
        frame_fetcher=frame_source,
        config=config,
        logger=logger,
    )
    server = api_server_module.ApiServer(provider, logger, offline_manager)
    thread = threading.Thread(
        target=server.serve_forever,
        args=(host, port),
        daemon=True,
        name="offline-screenshot-probe-no-device-server",
    )
    thread.start()
    return thread, provider, server


def run_probe(args: argparse.Namespace) -> dict[str, Any]:
    workspace_root = Path(args.workspace_root).resolve()
    api_server_path = workspace_root / "resource" / "pywrapper" / "api_server.py"
    static_scan = scan_screenshot_runtime_wiring(api_server_path)

    ensure_port_available(args.host, args.port, timeout_s=0.2)

    run_root = Path(args.run_root).resolve() if args.run_root else Path(tempfile.mkdtemp(prefix="ocr3_offline_probe_"))
    run_root.mkdir(parents=True, exist_ok=True)
    if args.runtime_mode == "no_device_fixed_data":
        runtime_info = prepare_no_device_runtime(workspace_root, run_root)
    else:
        runtime_info = prepare_runtime_copy(workspace_root, run_root)
    runtime_root = runtime_info["runtime_root"]
    probe_output_root = runtime_info["probe_output_root"]
    runtime_inventory_before = collect_probe_runtime_inventory(run_root, runtime_root, probe_output_root)
    process = None
    server_thread = None
    no_device_provider = None
    no_device_server = None
    if args.runtime_mode == "no_device_fixed_data":
        fixed_provider_payload = build_default_fixed_provider_data()
        if args.fixed_provider_json:
            fixed_provider_payload = json.loads(args.fixed_provider_json)
        server_thread, no_device_provider, no_device_server = launch_no_device_server(
            workspace_root,
            runtime_info,
            args.host,
            args.port,
            fixed_provider_payload,
        )
    else:
        exe_path = runtime_root / "ocrapp_pureray.exe"
        if not exe_path.exists():
            raise FileNotFoundError(f"server executable not found: {exe_path}")
        process = launch_server_process(exe_path)
    try:
        wait_for_server_ready(args.host, args.port, timeout_s=args.startup_timeout_s)

        probe_records: list[OnlineProbeRecord] = []
        stop_event = threading.Event()
        probe_start_ts = time.time()
        online_thread = threading.Thread(
            target=run_online_probe_loop,
            args=(args.host, args.port, args.password, args.probe_timeout_s, args.online_interval_s, stop_event, probe_records, probe_start_ts),
            daemon=True,
            name="offline-screenshot-probe-online",
        )
        online_thread.start()

        offline_payload = {
            "point_id": args.point_id,
            "time_out": args.offline_timeout_s,
            "is_save": True,
        }
        offline_start_ts = time.time()
        start_response, start_raw, _ = send_tcp_request(args.host, args.port, "OFFLINE", args.password, offline_payload, timeout_s=args.request_timeout_s)
        if not isinstance(start_response, dict) or start_response.get("info") != "offline_started":
            raise RuntimeError(f"OFFLINE start failed: {start_raw}")

        time.sleep(args.observation_window_s)

        offline_stop_ts = time.time()
        stop_response, stop_raw, _ = send_tcp_request(args.host, args.port, "OFFLINE", args.password, offline_payload, timeout_s=args.stop_timeout_s)
        if not isinstance(stop_response, dict) or stop_response.get("info") not in {"offline_stop_completed", "offline_stop_timeout"}:
            raise RuntimeError(f"OFFLINE stop failed: {stop_raw}")

        stop_event.set()
        online_thread.join(timeout=max(args.online_interval_s + args.probe_timeout_s + 1.0, 3.0))
        probe_end_ts = time.time()

        shutdown_response, shutdown_raw, _ = send_tcp_request(args.host, args.port, "SHUTDOWN", args.password, None, timeout_s=args.request_timeout_s)
        if not isinstance(shutdown_response, dict) or shutdown_response.get("info") != "shutdown_requested":
            raise RuntimeError(f"shutdown failed: {shutdown_raw}")
        wait_for_server_port_closed(args.host, args.port, timeout_s=args.shutdown_timeout_s)

        shutdown_cleanup_forced = False
        if process is not None:
            try:
                process.wait(timeout=args.shutdown_timeout_s)
            except subprocess.TimeoutExpired:
                shutdown_cleanup_forced = True
                process.terminate()
                process.wait(timeout=10.0)
        if server_thread is not None:
            server_thread.join(timeout=args.shutdown_timeout_s)
            if server_thread.is_alive():
                shutdown_cleanup_forced = True

        runtime_inventory_after = collect_probe_runtime_inventory(run_root, runtime_root, probe_output_root)
        created_files = sorted(runtime_inventory_after - runtime_inventory_before)
        log_text, log_excerpt = read_log_excerpt(runtime_root / "ocrlog" / "pywrapper_api_server.log")
        evidence = classify_runtime_evidence(log_text, created_files)
        expected_window_count = max(1, int(math.floor(args.observation_window_s / args.online_interval_s)))
        online_summary = summarize_online_records(probe_records, expected_window_count=expected_window_count)
        screenshot_frequency_hz = round(
            evidence["screenshot_event_count"] / max(args.observation_window_s, 1.0),
            6,
        )

        report = {
            "screenshot_config_enabled": True,
            "screenshot_flag_wired": static_scan["screenshot_flag_wired"],
            "screenshot_event_count": evidence["screenshot_event_count"],
            "screenshot_frequency_hz": screenshot_frequency_hz,
            "capture_sources_seen": evidence["capture_sources_seen"],
            "offline_start_ts": offline_start_ts,
            "offline_stop_ts": offline_stop_ts,
            "online_probe_count": online_summary["online_probe_count"],
            "online_success_count": online_summary["online_success_count"],
            "online_timeout_count": online_summary["online_timeout_count"],
            "online_missed_second_windows": online_summary["online_missed_second_windows"],
            "online_latency_ms": online_summary["online_latency_ms"],
            "online_empty_field_count": online_summary["online_empty_field_count"],
            "log_excerpt": log_excerpt,
            "created_files": created_files,
            "runtime_root": str(runtime_root),
            "runtime_settings_path": str(runtime_info["runtime_settings_path"]),
            "probe_output_root": str(probe_output_root),
            "matched_screenshot_tokens": static_scan["matched_tokens"],
            "shutdown_cleanup_forced": shutdown_cleanup_forced,
            "runtime_mode": args.runtime_mode,
        }
        report["final_conclusion"] = build_final_conclusion(report)
        report_paths = write_report_files(run_root, report)
        report.update(report_paths)
        return report
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
        if no_device_server is not None:
            try:
                no_device_server.request_shutdown()
            except Exception:
                pass
        if no_device_provider is not None:
            no_device_provider.close()
        if server_thread is not None and server_thread.is_alive():
            server_thread.join(timeout=5.0)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe the current OCR3 pywrapper OFFLINE/ONLINE behavior from an isolated packaged runtime copy.")
    parser.add_argument("--workspace-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--runtime-mode", choices=("packaged_real_device", "no_device_fixed_data"), default="packaged_real_device")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--observation-window-s", type=float, default=15.0)
    parser.add_argument("--offline-timeout-s", type=float, default=20.0)
    parser.add_argument("--online-interval-s", type=float, default=1.0)
    parser.add_argument("--probe-timeout-s", type=float, default=4.0)
    parser.add_argument("--request-timeout-s", type=float, default=3.0)
    parser.add_argument("--stop-timeout-s", type=float, default=25.0)
    parser.add_argument("--startup-timeout-s", type=float, default=20.0)
    parser.add_argument("--shutdown-timeout-s", type=float, default=10.0)
    parser.add_argument("--point-id", type=int, default=314159)
    parser.add_argument("--run-root")
    parser.add_argument("--fixed-provider-json")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    report = run_probe(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
