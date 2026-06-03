import importlib
import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


GUI_MODULES = [
    ("treatment_boundary_roi1_threshold_gui", "treatment_boundary_roi1_threshold", "ROI1 Full-Frame Threshold"),
    ("treatment_boundary_roi23_threshold_gui", "treatment_boundary_roi23_threshold", "ROI2/ROI3 Threshold"),
    ("treatment_boundary_frame_delta_gui", "treatment_boundary_frame_delta", "Adjacent Frame Delta"),
    ("treatment_boundary_bright_ratio_gui", "treatment_boundary_bright_ratio", "Bright Pixel Ratio"),
    ("treatment_boundary_peak_state_gui", "treatment_boundary_peak_state", "Peak State Machine"),
    ("treatment_boundary_file_size_gui", "treatment_boundary_file_size", "PNG File Size"),
]


class TreatmentBoundaryGuiFilesTest(unittest.TestCase):
    def test_gui_modules_import_without_creating_windows(self):
        for module_name, analyze_module, title in GUI_MODULES:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)

                self.assertEqual(module.ANALYZE_MODULE_NAME, analyze_module)
                self.assertEqual(module.METHOD_TITLE, title)
                self.assertTrue(callable(module.main))
                self.assertTrue(hasattr(module, "BoundaryGuiApp"))

    def test_resolve_result_image_paths_uses_detected_frame_names(self):
        folder = Path("E:/sample/folder")
        payload = {
            "before_frame": "00006_before.png",
            "after_frame": "00016_after.png",
        }
        for module_name, _analyze_module, _title in GUI_MODULES:
            with self.subTest(module=module_name):
                module = importlib.import_module(module_name)
                before_path, after_path = module.resolve_result_image_paths(folder, payload)

                self.assertEqual(before_path, folder / "00006_before.png")
                self.assertEqual(after_path, folder / "00016_after.png")


if __name__ == "__main__":
    unittest.main()
