import json
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication

import ultrasound_service


class FakeComm:
    def __init__(self):
        self.control_callback = None
        self.image_callback = None
        self.state_callback = None
        self.SetOnControlOnceMsg = Mock(side_effect=self._set_control_callback)
        self.SetOnImageInfoOnceMsg = Mock(side_effect=self._set_image_callback)
        self.SetOnClientStateInfoOnceMsg = Mock(side_effect=self._set_state_callback)
        self.SetD3DRenderHWND = Mock()
        self.RequestContentProvider = Mock()
        self.RestartAdbServer = Mock()
        self.Auto_Initialize = Mock(return_value=1)
        self.Stop_AutoInitialize = Mock()
        self.StreamRender = Mock()

    def _set_control_callback(self, callback):
        self.control_callback = callback

    def _set_image_callback(self, callback):
        self.image_callback = callback

    def _set_state_callback(self, callback):
        self.state_callback = callback


class UltrasoundServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.fake_comm = FakeComm()
        self.comm_patcher = patch.object(
            ultrasound_service.PyMobileComm,
            "CMobileCommunication",
            return_value=self.fake_comm,
        )
        self.comm_patcher.start()
        self.service = ultrasound_service.UltrasoundService()

    def tearDown(self):
        self.service._hidden_d3d_widget.deleteLater()
        self.service.deleteLater()
        self.comm_patcher.stop()
        self.app.processEvents()

    def test_request_provider_calls_request_content_provider(self):
        self.service.request_provider()

        self.fake_comm.RequestContentProvider.assert_called_once_with()

    def test_control_callback_emits_standardized_provider_payload(self):
        emitted = []
        self.service.provider_updated.connect(emitted.append)

        self.service._on_control_received(
            json.dumps(
                {
                    "focus_depth": "7.5",
                    "guankuan_a": "10.1",
                    "guankuan_b": "20.2",
                    "depth": "35",
                    "isLive": True,
                    "mode": 2,
                    "focus_x": "111.25",
                    "focus_y": "222.5",
                }
            )
        )
        self.app.processEvents()

        self.assertEqual(
            emitted,
            [
                {
                    "SkinDepth": "-1",
                    "A": "10.1",
                    "B": "20.2",
                    "Alpha": None,
                    "Depth": "35",
                    "IsFreeze": False,
                    "isHIFU": True,
                    "FocusPoint": "PointF(111.25, 222.5)",
                }
            ],
        )

    def test_control_callback_extracts_json_from_wrapped_string_payload(self):
        emitted = []
        self.service.provider_updated.connect(emitted.append)

        self.service._on_control_received(
            'provider={"focus_depth":"7.5","guankuan_a":"10.1","guankuan_b":"20.2","depth":"35","isLive":true,"mode":2,"focus_x":"111.25","focus_y":"222.5"} trailing text'
        )
        self.app.processEvents()

        self.assertEqual(
            emitted,
            [
                {
                    "SkinDepth": "-1",
                    "A": "10.1",
                    "B": "20.2",
                    "Alpha": None,
                    "Depth": "35",
                    "IsFreeze": False,
                    "isHIFU": True,
                    "FocusPoint": "PointF(111.25, 222.5)",
                }
            ],
        )

    def test_control_callback_emits_empty_payload_when_json_missing(self):
        emitted = []
        self.service.provider_updated.connect(emitted.append)

        self.service._on_control_received("provider callback without json")
        self.app.processEvents()

        self.assertEqual(emitted, [{}])


if __name__ == "__main__":
    unittest.main()
