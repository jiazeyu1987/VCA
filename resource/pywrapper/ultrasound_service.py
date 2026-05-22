import ctypes
import json
import logging
import os
import queue
import re
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QWidget

EXTERNAL_RUNTIME_DIR = Path(r"D:\ocr3\resource\pywrapper")
REQUIRED_RUNTIME_FILES = (
    "PyMobileComm.pyd",
    "MobileCommunication.dll",
)


def runtime_has_required_files(base_dir: Path) -> bool:
    return all((base_dir / name).exists() for name in REQUIRED_RUNTIME_FILES)


def resolve_runtime_dir(base_dir: Path) -> Path:
    env_value = os.environ.get("PYWRAPPER_RUNTIME_DIR")
    candidates = []
    if env_value:
        candidates.append(Path(env_value))
    candidates.append(base_dir)
    candidates.append(EXTERNAL_RUNTIME_DIR)
    for candidate in candidates:
        if candidate.exists() and runtime_has_required_files(candidate):
            return candidate
    return base_dir


def configure_runtime_paths() -> None:
    base_dir = Path(__file__).resolve().parent
    runtime_dir = resolve_runtime_dir(base_dir)
    os.add_dll_directory(str(runtime_dir))
    runtime_text = str(runtime_dir)
    if runtime_text not in sys.path:
        sys.path.insert(0, runtime_text)


configure_runtime_paths()
import PyMobileComm


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


class UltrasoundService(QObject):
    state_updated = pyqtSignal(object)
    frame_received = pyqtSignal(object)
    provider_updated = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.stream_queue = queue.Queue(maxsize=100)
        self._hidden_d3d_widget = QWidget()
        self._hidden_d3d_widget.hide()
        self.hwnd = int(self._hidden_d3d_widget.winId())

        self.comm = PyMobileComm.CMobileCommunication()
        self.comm.SetOnControlOnceMsg(self._on_control_received)
        self.comm.SetOnImageInfoOnceMsg(self._on_stream_data_received)
        self.comm.SetOnClientStateInfoOnceMsg(self._on_state_info_received)
        self.comm.SetD3DRenderHWND(self.hwnd)
        logging.info("hidden D3D widget initialized hwnd=%s", self.hwnd)

        self.engine_timer = QTimer(self)
        self.engine_timer.timeout.connect(self._engine_tick)

        self.algo_timer = QTimer(self)
        self.algo_timer.timeout.connect(self._process_stream_queue)

    def _convert_to_standard_format(self, raw_data: dict) -> dict:
        if not raw_data:
            return {}

        is_live = raw_data.get("isLive")
        is_freeze = not is_live if is_live is not None else None
        is_hifu = raw_data.get("mode") == 2
        focus_point = raw_data.get("focus_point")
        if focus_point is None and raw_data.get("focus_x") is not None and raw_data.get("focus_y") is not None:
            focus_point = f'PointF({raw_data.get("focus_x")}, {raw_data.get("focus_y")})'

        return {
            "SkinDepth": "-1",
            "A": raw_data.get("guankuan_a"),
            "B": raw_data.get("guankuan_b"),
            "Alpha": raw_data.get("Alpha"),
            "Depth": raw_data.get("depth"),
            "IsFreeze": is_freeze,
            "isHIFU": is_hifu,
            "FocusPoint": focus_point,
        }

    def extract_valid_json(self, raw_str):
        match = re.search(r"\{.*?\}.*?", raw_str, re.DOTALL)

        if match:
            try:
                json_str = match.group(0)
                json_str = json_str[: json_str.rfind("}") + 1]
                return json.loads(json_str)
            except json.JSONDecodeError:
                print(f"Extracted JSON still failed to parse: {json_str}")
                return None
        else:
            print(f"No valid JSON structure found in string: {raw_str}")
            return None

    def _on_control_received(self, raw_string):
        print(raw_string)
        provider_dict = self.extract_valid_json(raw_string)

        print(f"[Python final extracted dict]: {provider_dict}")

        result = self._convert_to_standard_format(provider_dict)
        self.provider_updated.emit(result)

    def _on_stream_data_received(self, header_ptr, image_matrix):
        try:
            self.stream_queue.put_nowait(image_matrix)
        except queue.Full:
            pass

    def _on_state_info_received(self, error_info_ptr):
        if error_info_ptr != 0:
            state = ctypes.cast(error_info_ptr, ctypes.POINTER(StateInfo)).contents
            self.state_updated.emit(state)

    def start_engine(self):
        subprocess.run(["adb", "devices"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.comm.RestartAdbServer()
        time.sleep(1)

        is_init = self.comm.Auto_Initialize()
        if is_init:
            logging.info("Auto_Initialize succeeded")
        else:
            logging.error("Auto_Initialize failed")

        self.engine_timer.start(16)
        self.algo_timer.start(10)

    def stop_engine(self):
        self.engine_timer.stop()
        self.algo_timer.stop()
        self.comm.Stop_AutoInitialize()
        self._hidden_d3d_widget.deleteLater()

    def _engine_tick(self):
        msg = wintypes.MSG()
        while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
            ctypes.windll.user32.TranslateMessage(ctypes.byref(msg))
            ctypes.windll.user32.DispatchMessageW(ctypes.byref(msg))
        self.comm.StreamRender()

    def _process_stream_queue(self):
        try:
            while not self.stream_queue.empty():
                image_matrix = self.stream_queue.get_nowait()
                self.frame_received.emit(image_matrix)
                self.stream_queue.task_done()
        except Exception:
            logging.exception("failed to process stream queue")

    def request_provider(self):
        self.comm.RequestContentProvider()
