import importlib.util
import tempfile
from pathlib import Path
import unittest


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = WORKSPACE_ROOT / "tools" / "test_ocr_client_gui.py"


def load_client_module():
    spec = importlib.util.spec_from_file_location("test_ocr_client_gui", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestOcrClientGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = load_client_module()

    def test_module_exists(self):
        self.assertTrue(MODULE_PATH.exists(), MODULE_PATH)

    def test_point_id_pair_generator_emits_each_id_exactly_twice(self):
        generator = self.client.PointIdPairGenerator(seed=7, min_value=1000, max_value=9999)

        emitted = [generator.next_point_id() for _ in range(6)]

        self.assertEqual(emitted[0], emitted[1])
        self.assertEqual(emitted[2], emitted[3])
        self.assertEqual(emitted[4], emitted[5])
        self.assertNotEqual(emitted[0], emitted[2])
        self.assertNotEqual(emitted[2], emitted[4])
        self.assertEqual({value: emitted.count(value) for value in set(emitted)}, {emitted[0]: 2, emitted[2]: 2, emitted[4]: 2})

    def test_save_and_load_client_config_round_trips_goal_text(self):
        config = self.client.ClientConfig(
            host="127.0.0.1",
            port=30415,
            password="31415",
            online_interval_s=1.0,
            offline_interval_s=5.0,
            offline_timeout_s=20.0,
            request_timeout_s=8.0,
            is_save=True,
            goal_text="自定义目标文本",
        )

        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "client_config.json"
            self.client.save_client_config(config_path, config)

            loaded = self.client.load_client_config(config_path)

        self.assertEqual(loaded.goal_text, "自定义目标文本")
        self.assertEqual(loaded.host, "127.0.0.1")
        self.assertEqual(loaded.port, 30415)
        self.assertTrue(loaded.is_save)

    def test_extract_screenshot_paths_preserves_expected_keys(self):
        response = {
            "before_path": "D:/tmp/before.png",
            "after_path": "D:/tmp/after.png",
            "diff_path": "D:/tmp/diff.png",
        }

        paths = self.client.extract_screenshot_paths(response)

        self.assertEqual(
            paths,
            {
                "before_path": "D:/tmp/before.png",
                "after_path": "D:/tmp/after.png",
                "diff_path": "D:/tmp/diff.png",
            },
        )

    def test_launcher_bat_targets_single_file_gui_script(self):
        batch_path = WORKSPACE_ROOT / "run_test_ocr_client_gui.bat"

        self.assertTrue(batch_path.exists(), batch_path)
        text = batch_path.read_text(encoding="utf-8")
        self.assertIn(r"tools\test_ocr_client_gui.py", text)
        self.assertIn("PYTHON_EXE", text)


if __name__ == "__main__":
    unittest.main()
