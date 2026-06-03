import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent


BAT_TO_GUI = {
    "run_treatment_boundary_roi1_threshold.bat": r"tools\treatment_boundary_roi1_threshold_gui.py",
    "run_treatment_boundary_roi23_threshold.bat": r"tools\treatment_boundary_roi23_threshold_gui.py",
    "run_treatment_boundary_frame_delta.bat": r"tools\treatment_boundary_frame_delta_gui.py",
    "run_treatment_boundary_bright_ratio.bat": r"tools\treatment_boundary_bright_ratio_gui.py",
    "run_treatment_boundary_peak_state.bat": r"tools\treatment_boundary_peak_state_gui.py",
    "run_treatment_boundary_file_size.bat": r"tools\treatment_boundary_file_size_gui.py",
}


class TreatmentBoundaryGuiBatRunnersTest(unittest.TestCase):
    def test_bat_runners_point_to_gui_files(self):
        for bat_name, gui_relative_path in BAT_TO_GUI.items():
            with self.subTest(bat=bat_name):
                text = (ROOT_DIR / bat_name).read_text(encoding="utf-8")

                self.assertIn(gui_relative_path, text)
                self.assertNotIn("--folder", text)
                self.assertNotIn("107969_20260601_171819_175", text)


if __name__ == "__main__":
    unittest.main()
