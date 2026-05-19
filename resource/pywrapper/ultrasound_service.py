import ctypes
import subprocess
import time
import logging
import queue
import os
import sys
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


# 保留原有的结构体定义
class HeaderCtrl(ctypes.Structure):
    _fields_ = [("operation", ctypes.c_int), ("value", ctypes.c_int), ("ext_len", ctypes.c_int)]


class StateInfo(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_int), ("AdbServer", ctypes.c_int), ("LicenseType", ctypes.c_int),
        ("ControlLinkState", ctypes.c_int), ("ImageInfoLinkState", ctypes.c_int),
        ("USBLinkState", ctypes.c_int), ("AppRunState", ctypes.c_int),
    ]


class UltrasoundService(QObject):
    state_updated = pyqtSignal(object)
    frame_received = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.stream_queue = queue.Queue(maxsize=100)

        # 核心：创建一个无父对象的隐藏 QWidget，专门为了骗取 HWND 供 D3D 渲染使用
        self._hidden_d3d_widget = QWidget()
        self._hidden_d3d_widget.hide()
        self.hwnd = int(self._hidden_d3d_widget.winId())

        # 引擎初始化
        self.comm = PyMobileComm.CMobileCommunication()

        # 绑定 C++ 回调机制 (使用实例方法或闭包)
        self.comm.SetOnClientOnceMsg(self._on_control_msg_received)
        self.comm.SetOnImageInfoOnceMsg(self._on_stream_data_received)
        self.comm.SetOnClientStateInfoOnceMsg(self._on_state_info_received)

        self.comm.SetD3DRenderHWND(self.hwnd)
        logging.info(f"🎨 后台隐藏画板(HWND={self.hwnd})已注入")

        # 定时器设置
        self.engine_timer = QTimer(self)
        self.engine_timer.timeout.connect(self._engine_tick)

        self.algo_timer = QTimer(self)
        self.algo_timer.timeout.connect(self._process_stream_queue)

    # ==========================================
    # C++ 回调函数封装
    # ==========================================
    def _on_control_msg_received(self, header_ptr, data_bytes):
        pass

    def _on_stream_data_received(self, header_ptr, image_matrix):
        try:
            self.stream_queue.put_nowait(image_matrix)
        except queue.Full:
            pass

    def _on_state_info_received(self, error_info_ptr):
        if error_info_ptr != 0:
            state = ctypes.cast(error_info_ptr, ctypes.POINTER(StateInfo)).contents
            self.state_updated.emit(state)

    # ==========================================
    # 核心生命周期控制
    # ==========================================
    def start_engine(self):
        """点火启动引擎，开始拉取数据"""
        subprocess.run(["adb", "devices"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.comm.RestartAdbServer()
        time.sleep(1)
        self.comm.Auto_Initialize()
        logging.info("🚀 超声底层引擎初始化完成！")

        self.engine_timer.start(16)  # ~60FPS
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

    def _convert_to_standard_format(self,raw_data: dict) -> dict:
        if not raw_data:
            return {}

        is_live = raw_data.get('isLive')
        is_freeze = not is_live if is_live is not None else None
        is_HIFU = raw_data.get('mode') == 2
        print(raw_data)
        standard_data = {
            "SkinDepth": "-1",
            "A": raw_data.get('guankuan_a'),
            "B": raw_data.get('guankuan_b'),
            "Alpha": raw_data.get('Alpha'),
            "Depth": raw_data.get('depth'),
            "IsFreeze": is_freeze,
            "isHIFU": is_HIFU,
            "FocusPoint": raw_data.get('focus_point'),
        }

        return standard_data

    def _process_stream_queue(self):
        try:
            while not self.stream_queue.empty():
                image_matrix = self.stream_queue.get_nowait()
                self.frame_received.emit(image_matrix)
                self.stream_queue.task_done()
        except Exception:
            pass

    def fetch_provider(self) -> dict:
        try:
            info_dict = self.comm.GetContentProvider()
            return self._convert_to_standard_format(info_dict) if info_dict else {}
        except Exception as e:
            logging.error(f"获取 Provider 异常: {e}")
            return {}
