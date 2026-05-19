from __future__ import annotations

import json
import random
import socket
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from tkinter import messagebox, ttk
from typing import Any, Optional

from PIL import Image, ImageTk


DEFAULT_CONFIG_PATH = Path(__file__).with_name("test_ocr_client_gui_config.json")
DEFAULT_GOAL_TEXT = (
    "每条发送一次online命令,要保证每次都要返回,不管offline命令发送如何,"
    "offline命令每5秒随机发送一个,但是point_id要成对,也就是必须有也只能有两个相同的point_id"
)
SCREENSHOT_KEYS = ("before_path", "after_path", "diff_path")


@dataclass
class ClientConfig:
    host: str = "127.0.0.1"
    port: int = 30415
    password: str = "31415"
    online_interval_s: float = 1.0
    offline_interval_s: float = 5.0
    offline_timeout_s: float = 20.0
    request_timeout_s: float = 8.0
    is_save: bool = True
    goal_text: str = DEFAULT_GOAL_TEXT

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "password": self.password,
            "online_interval_s": self.online_interval_s,
            "offline_interval_s": self.offline_interval_s,
            "offline_timeout_s": self.offline_timeout_s,
            "request_timeout_s": self.request_timeout_s,
            "is_save": self.is_save,
            "goal_text": self.goal_text,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ClientConfig":
        required_keys = {
            "host",
            "port",
            "password",
            "online_interval_s",
            "offline_interval_s",
            "offline_timeout_s",
            "request_timeout_s",
            "is_save",
            "goal_text",
        }
        missing = sorted(required_keys - set(payload.keys()))
        if missing:
            raise ValueError(f"client config missing required keys: {', '.join(missing)}")
        return cls(
            host=str(payload["host"]).strip(),
            port=int(payload["port"]),
            password=str(payload["password"]).strip(),
            online_interval_s=float(payload["online_interval_s"]),
            offline_interval_s=float(payload["offline_interval_s"]),
            offline_timeout_s=float(payload["offline_timeout_s"]),
            request_timeout_s=float(payload["request_timeout_s"]),
            is_save=bool(payload["is_save"]),
            goal_text=str(payload["goal_text"]).strip(),
        )


class PointIdPairGenerator:
    def __init__(self, seed: Optional[int] = None, min_value: int = 100000, max_value: int = 999999):
        if min_value > max_value:
            raise ValueError("point_id min_value must be <= max_value")
        self._rng = random.Random(seed)
        self._min_value = int(min_value)
        self._max_value = int(max_value)
        self._used_ids: set[int] = set()
        self._pending_second: Optional[int] = None

    def next_point_id(self) -> int:
        if self._pending_second is not None:
            point_id = self._pending_second
            self._pending_second = None
            return point_id

        available_count = self._max_value - self._min_value + 1
        if len(self._used_ids) >= available_count:
            raise RuntimeError("point_id range exhausted; no unique pair ids remain")

        while True:
            candidate = self._rng.randint(self._min_value, self._max_value)
            if candidate in self._used_ids:
                continue
            self._used_ids.add(candidate)
            self._pending_second = candidate
            return candidate


def load_client_config(path: Path) -> ClientConfig:
    if not path.exists():
        return ClientConfig()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"client config is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"client config root must be a JSON object: {path}")
    return ClientConfig.from_dict(payload)


def save_client_config(path: Path, config: ClientConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def build_request_text(req_type: str, password: str, payload: Optional[dict[str, Any]]) -> str:
    request_type = str(req_type).strip().upper()
    if not request_type:
        raise ValueError("request type is empty")
    password_text = str(password).strip()
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

    raw_lines = b"".join(chunks).decode("utf-8", errors="replace").splitlines()
    response_text = raw_lines[0].strip() if raw_lines else ""
    if not response_text:
        return None, response_text, recv_timed_out
    try:
        return json.loads(response_text), response_text, recv_timed_out
    except json.JSONDecodeError:
        return None, response_text, recv_timed_out


def build_offline_payload(point_id: int, timeout_s: float, is_save: bool) -> dict[str, Any]:
    return {
        "point_id": int(point_id),
        "time_out": float(timeout_s),
        "is_save": bool(is_save),
    }


def extract_screenshot_paths(response: Optional[dict[str, Any]]) -> dict[str, str]:
    if not isinstance(response, dict):
        return {}
    result: dict[str, str] = {}
    for key in SCREENSHOT_KEYS:
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


class SimulatorApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("OCR3 测试模拟器")
        self.root.geometry("1480x920")
        self.root.minsize(1180, 760)

        self.config_path = DEFAULT_CONFIG_PATH
        self.current_config = load_client_config(self.config_path)
        self.ui_queue: Queue[dict[str, Any]] = Queue()
        self.stop_event: Optional[threading.Event] = None
        self.threads: list[threading.Thread] = []
        self.running = False
        self.point_id_generator = PointIdPairGenerator(seed=int(time.time_ns() & 0xFFFFFFFF))
        self.preview_photo_refs: dict[str, ImageTk.PhotoImage] = {}
        self.stats = {
            "online_sent": 0,
            "online_returned": 0,
            "online_errors": 0,
            "offline_sent": 0,
            "offline_returned": 0,
            "offline_errors": 0,
        }

        self.host_var = tk.StringVar()
        self.port_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.online_interval_var = tk.StringVar()
        self.offline_interval_var = tk.StringVar()
        self.offline_timeout_var = tk.StringVar()
        self.request_timeout_var = tk.StringVar()
        self.is_save_var = tk.BooleanVar()
        self.status_var = tk.StringVar(value="未启动")
        self.stats_var = tk.StringVar()
        self.config_path_var = tk.StringVar(value=str(self.config_path))
        self.preview_path_vars = {key: tk.StringVar(value="") for key in SCREENSHOT_KEYS}

        self._build_layout()
        self._load_config_into_controls(self.current_config)
        self._refresh_stats_text()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._drain_ui_queue)

    def _build_layout(self) -> None:
        root_frame = ttk.Frame(self.root, padding=12)
        root_frame.pack(fill="both", expand=True)
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(1, weight=1)
        root_frame.rowconfigure(2, weight=0)

        control_frame = ttk.LabelFrame(root_frame, text="运行配置", padding=10)
        control_frame.grid(row=0, column=0, sticky="ew")
        for index in range(8):
            control_frame.columnconfigure(index, weight=1 if index % 2 == 1 else 0)

        self._add_labeled_entry(control_frame, "Host", self.host_var, 0, 0)
        self._add_labeled_entry(control_frame, "Port", self.port_var, 0, 2)
        self._add_labeled_entry(control_frame, "Password", self.password_var, 0, 4, show="*")
        self._add_labeled_entry(control_frame, "ONLINE 间隔(s)", self.online_interval_var, 1, 0)
        self._add_labeled_entry(control_frame, "OFFLINE 间隔(s)", self.offline_interval_var, 1, 2)
        self._add_labeled_entry(control_frame, "OFFLINE time_out(s)", self.offline_timeout_var, 1, 4)
        self._add_labeled_entry(control_frame, "请求超时(s)", self.request_timeout_var, 1, 6)

        is_save_button = ttk.Checkbutton(control_frame, text="OFFLINE is_save=true", variable=self.is_save_var)
        is_save_button.grid(row=0, column=6, sticky="w", padx=(12, 8), pady=6)

        button_frame = ttk.Frame(control_frame)
        button_frame.grid(row=2, column=0, columnspan=8, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(5, weight=1)

        self.start_button = ttk.Button(button_frame, text="启动模拟", command=self.start_simulation)
        self.start_button.grid(row=0, column=0, padx=(0, 8))
        self.stop_button = ttk.Button(button_frame, text="停止模拟", command=self.stop_simulation, state="disabled")
        self.stop_button.grid(row=0, column=1, padx=(0, 8))
        save_button = ttk.Button(button_frame, text="保存目标/配置", command=self.save_current_config)
        save_button.grid(row=0, column=2, padx=(0, 8))
        clear_button = ttk.Button(button_frame, text="清空日志", command=self.clear_log)
        clear_button.grid(row=0, column=3, padx=(0, 8))

        ttk.Label(button_frame, text="状态:").grid(row=0, column=4, sticky="e")
        ttk.Label(button_frame, textvariable=self.status_var).grid(row=0, column=5, sticky="w", padx=(6, 0))

        ttk.Label(button_frame, text="配置文件:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(button_frame, textvariable=self.config_path_var).grid(row=1, column=1, columnspan=7, sticky="w", pady=(8, 0))

        center_pane = ttk.PanedWindow(root_frame, orient="horizontal")
        center_pane.grid(row=1, column=0, sticky="nsew", pady=(12, 12))

        goal_frame = ttk.LabelFrame(center_pane, text="目标", padding=10)
        goal_frame.columnconfigure(0, weight=1)
        goal_frame.rowconfigure(0, weight=1)
        self.goal_text = tk.Text(goal_frame, wrap="word", font=("Microsoft YaHei UI", 11))
        self.goal_text.grid(row=0, column=0, sticky="nsew")
        goal_scroll = ttk.Scrollbar(goal_frame, orient="vertical", command=self.goal_text.yview)
        goal_scroll.grid(row=0, column=1, sticky="ns")
        self.goal_text.configure(yscrollcommand=goal_scroll.set)
        center_pane.add(goal_frame, weight=1)

        log_frame = ttk.LabelFrame(center_pane, text="运行日志", padding=10)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        ttk.Label(log_frame, textvariable=self.stats_var).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.log_text = tk.Text(log_frame, wrap="word", font=("Consolas", 10), state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=1, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)
        center_pane.add(log_frame, weight=2)

        screenshot_frame = ttk.LabelFrame(root_frame, text="最新截图返回", padding=10)
        screenshot_frame.grid(row=2, column=0, sticky="ew")
        for index in range(3):
            screenshot_frame.columnconfigure(index, weight=1)

        self.preview_widgets: dict[str, dict[str, Any]] = {}
        for index, key in enumerate(SCREENSHOT_KEYS):
            frame = ttk.Frame(screenshot_frame, padding=6)
            frame.grid(row=0, column=index, sticky="nsew")
            frame.columnconfigure(0, weight=1)
            ttk.Label(frame, text=key).grid(row=0, column=0, sticky="w")
            image_label = ttk.Label(frame, text="暂无截图", anchor="center")
            image_label.grid(row=1, column=0, sticky="nsew", pady=(8, 8))
            path_label = ttk.Label(frame, textvariable=self.preview_path_vars[key], wraplength=420, justify="left")
            path_label.grid(row=2, column=0, sticky="w")
            self.preview_widgets[key] = {
                "image_label": image_label,
                "path_label": path_label,
            }

    def _add_labeled_entry(
        self,
        parent: ttk.Widget,
        label_text: str,
        variable: tk.StringVar,
        row: int,
        column: int,
        show: Optional[str] = None,
    ) -> None:
        ttk.Label(parent, text=label_text).grid(row=row, column=column, sticky="w", padx=(0, 8), pady=6)
        entry = ttk.Entry(parent, textvariable=variable, show=show or "")
        entry.grid(row=row, column=column + 1, sticky="ew", padx=(0, 12), pady=6)

    def _load_config_into_controls(self, config: ClientConfig) -> None:
        self.host_var.set(config.host)
        self.port_var.set(str(config.port))
        self.password_var.set(config.password)
        self.online_interval_var.set(str(config.online_interval_s))
        self.offline_interval_var.set(str(config.offline_interval_s))
        self.offline_timeout_var.set(str(config.offline_timeout_s))
        self.request_timeout_var.set(str(config.request_timeout_s))
        self.is_save_var.set(bool(config.is_save))
        self.goal_text.delete("1.0", "end")
        self.goal_text.insert("1.0", config.goal_text)

    def _read_config_from_controls(self) -> ClientConfig:
        host = self.host_var.get().strip()
        if not host:
            raise ValueError("Host 不能为空")

        password = self.password_var.get().strip()
        if not password:
            raise ValueError("Password 不能为空")

        goal_text = self.goal_text.get("1.0", "end").strip()
        if not goal_text:
            raise ValueError("目标文本不能为空")

        port = int(self.port_var.get().strip())
        online_interval_s = float(self.online_interval_var.get().strip())
        offline_interval_s = float(self.offline_interval_var.get().strip())
        offline_timeout_s = float(self.offline_timeout_var.get().strip())
        request_timeout_s = float(self.request_timeout_var.get().strip())

        if port <= 0:
            raise ValueError("Port 必须大于 0")
        if online_interval_s <= 0:
            raise ValueError("ONLINE 间隔必须大于 0")
        if offline_interval_s <= 0:
            raise ValueError("OFFLINE 间隔必须大于 0")
        if offline_timeout_s <= 0:
            raise ValueError("OFFLINE time_out 必须大于 0")
        if request_timeout_s <= 0:
            raise ValueError("请求超时必须大于 0")

        return ClientConfig(
            host=host,
            port=port,
            password=password,
            online_interval_s=online_interval_s,
            offline_interval_s=offline_interval_s,
            offline_timeout_s=offline_timeout_s,
            request_timeout_s=request_timeout_s,
            is_save=self.is_save_var.get(),
            goal_text=goal_text,
        )

    def save_current_config(self) -> None:
        try:
            config = self._read_config_from_controls()
            save_client_config(self.config_path, config)
        except Exception as exc:
            self.status_var.set("保存失败")
            self._append_log_line(f"[ERROR] 保存配置失败: {exc}")
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return

        self.current_config = config
        self.status_var.set("已保存")
        self._append_log_line(f"[INFO] 配置已保存: {self.config_path}")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def start_simulation(self) -> None:
        if self.running:
            return
        try:
            config = self._read_config_from_controls()
            response, raw_text, recv_timed_out = send_tcp_request(
                config.host,
                config.port,
                "ONLINE",
                config.password,
                {},
                config.request_timeout_s,
            )
        except Exception as exc:
            self.status_var.set("启动失败")
            self._append_log_line(f"[ERROR] 启动前 ONLINE 预检查失败: {exc}")
            messagebox.showerror("启动失败", f"无法连接或预检查失败:\n{exc}", parent=self.root)
            return

        if recv_timed_out or response is None:
            self.status_var.set("启动失败")
            self._append_log_line("[ERROR] 启动前 ONLINE 预检查未收到合法 JSON 返回")
            messagebox.showerror("启动失败", "ONLINE 预检查未收到合法 JSON 返回", parent=self.root)
            return

        if isinstance(response, dict) and response.get("success") is False:
            info = response.get("info", "unknown_error")
            self.status_var.set("启动失败")
            self._append_log_line(f"[ERROR] 启动前 ONLINE 预检查返回失败: {info}")
            messagebox.showerror("启动失败", f"ONLINE 预检查返回失败: {info}", parent=self.root)
            return

        self.current_config = config
        self.running = True
        self.stats = {
            "online_sent": 0,
            "online_returned": 0,
            "online_errors": 0,
            "offline_sent": 0,
            "offline_returned": 0,
            "offline_errors": 0,
        }
        self._refresh_stats_text()
        self._clear_preview_widgets()
        self.point_id_generator = PointIdPairGenerator(seed=int(time.time_ns() & 0xFFFFFFFF))
        self.stop_event = threading.Event()
        self.threads = [
            threading.Thread(
                target=self._run_online_loop,
                args=(config, self.stop_event),
                name="ocr3-test-online-loop",
                daemon=True,
            ),
            threading.Thread(
                target=self._run_offline_loop,
                args=(config, self.stop_event),
                name="ocr3-test-offline-loop",
                daemon=True,
            ),
        ]
        for thread in self.threads:
            thread.start()

        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("运行中")
        self._append_log_line("[INFO] 模拟器已启动")
        self._append_log_line(f"[INFO] ONLINE 预检查返回: {json.dumps(response or raw_text, ensure_ascii=False)}")

    def stop_simulation(self) -> None:
        if not self.running:
            return
        if self.stop_event is not None:
            self.stop_event.set()
        self.running = False
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.status_var.set("已停止")
        self._append_log_line("[INFO] 已请求停止模拟器")

    def on_close(self) -> None:
        self.stop_simulation()
        self.root.destroy()

    def _run_online_loop(self, config: ClientConfig, stop_event: threading.Event) -> None:
        next_tick = time.monotonic()
        while not stop_event.is_set():
            wait_s = max(0.0, next_tick - time.monotonic())
            if wait_s > 0 and stop_event.wait(wait_s):
                break

            started_at = time.time()
            self._queue_stats({"online_sent": 1})
            try:
                response, raw_text, recv_timed_out = send_tcp_request(
                    config.host,
                    config.port,
                    "ONLINE",
                    config.password,
                    {},
                    config.request_timeout_s,
                )
            except Exception as exc:
                self._queue_stats({"online_errors": 1})
                self._queue_log(f"[ERROR] ONLINE 异常: {exc}")
            else:
                latency_ms = round((time.time() - started_at) * 1000.0, 2)
                if recv_timed_out or response is None:
                    self._queue_stats({"online_errors": 1})
                    self._queue_log(f"[ERROR] ONLINE 未返回合法 JSON, latency_ms={latency_ms}, raw={raw_text}")
                else:
                    self._queue_stats({"online_returned": 1})
                    response_text = json.dumps(response, ensure_ascii=False) if response is not None else raw_text
                    self._queue_log(f"[ONLINE] latency_ms={latency_ms} response={response_text}")

            next_tick += config.online_interval_s
            if next_tick < time.monotonic():
                next_tick = time.monotonic()

    def _run_offline_loop(self, config: ClientConfig, stop_event: threading.Event) -> None:
        next_tick = time.monotonic() + config.offline_interval_s
        send_index = 0
        while not stop_event.is_set():
            wait_s = max(0.0, next_tick - time.monotonic())
            if wait_s > 0 and stop_event.wait(wait_s):
                break

            send_index += 1
            point_id = self.point_id_generator.next_point_id()
            phase = "start" if send_index % 2 == 1 else "stop"
            payload = build_offline_payload(point_id, config.offline_timeout_s, config.is_save)
            self._queue_stats({"offline_sent": 1})

            try:
                response, raw_text, recv_timed_out = send_tcp_request(
                    config.host,
                    config.port,
                    "OFFLINE",
                    config.password,
                    payload,
                    config.request_timeout_s,
                )
            except Exception as exc:
                self._queue_stats({"offline_errors": 1})
                self._queue_log(f"[ERROR] OFFLINE {phase} point_id={point_id} 异常: {exc}")
            else:
                if recv_timed_out or response is None:
                    self._queue_stats({"offline_errors": 1})
                    self._queue_log(f"[ERROR] OFFLINE {phase} point_id={point_id} 未返回合法 JSON, raw={raw_text}")
                else:
                    self._queue_stats({"offline_returned": 1})
                    response_text = json.dumps(response, ensure_ascii=False) if response is not None else raw_text
                    self._queue_log(f"[OFFLINE-{phase}] point_id={point_id} response={response_text}")
                    screenshot_paths = extract_screenshot_paths(response)
                    if screenshot_paths:
                        self.ui_queue.put({"kind": "preview", "paths": screenshot_paths})
                    elif phase == "stop":
                        self._queue_log(f"[WARN] OFFLINE stop point_id={point_id} 未返回截图路径")

            next_tick += config.offline_interval_s
            if next_tick < time.monotonic():
                next_tick = time.monotonic()

    def _queue_log(self, message: str) -> None:
        self.ui_queue.put({"kind": "log", "message": message})

    def _queue_stats(self, delta: dict[str, int]) -> None:
        self.ui_queue.put({"kind": "stats", "delta": delta})

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item.get("kind")
                if kind == "log":
                    self._append_log_line(str(item.get("message", "")))
                elif kind == "stats":
                    for key, value in dict(item.get("delta", {})).items():
                        self.stats[key] = self.stats.get(key, 0) + int(value)
                    self._refresh_stats_text()
                elif kind == "preview":
                    self._update_preview_widgets(dict(item.get("paths", {})))
        except Empty:
            pass
        try:
            if self.root.winfo_exists():
                self.root.after(100, self._drain_ui_queue)
        except tk.TclError:
            return

    def _append_log_line(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{timestamp} {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _refresh_stats_text(self) -> None:
        self.stats_var.set(
            "ONLINE sent={online_sent} returned={online_returned} errors={online_errors} | "
            "OFFLINE sent={offline_sent} returned={offline_returned} errors={offline_errors}".format(**self.stats)
        )

    def _clear_preview_widgets(self) -> None:
        self.preview_photo_refs.clear()
        for key in SCREENSHOT_KEYS:
            self.preview_path_vars[key].set("")
            self.preview_widgets[key]["image_label"].configure(image="", text="暂无截图")

    def _update_preview_widgets(self, paths: dict[str, str]) -> None:
        for key in SCREENSHOT_KEYS:
            path_text = paths.get(key, "")
            self.preview_path_vars[key].set(path_text)
            widget = self.preview_widgets[key]["image_label"]
            if not path_text:
                widget.configure(image="", text="暂无截图")
                continue

            path = Path(path_text)
            if not path.exists():
                widget.configure(image="", text="截图路径不存在")
                self._append_log_line(f"[WARN] {key} 路径不存在: {path}")
                continue

            with Image.open(path) as image:
                preview = image.copy()
            preview.thumbnail((420, 240))
            photo = ImageTk.PhotoImage(preview)
            self.preview_photo_refs[key] = photo
            widget.configure(image=photo, text="")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = SimulatorApp()
    app.run()


if __name__ == "__main__":
    main()
