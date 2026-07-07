# HEM ROI Save Anchor Lock

## Goal
- Add a clear ROI/highlight save button label for the GUI.
- When ROI inputs are blank, saving uses the currently displayed ROI1~ROI4 preview rectangles and shapes.
- After saving, later focus-point changes must not move saved rectangle or ellipse ROI centers.

## Milestones
- [x] Create task documentation and inspect current save behavior.
- [x] Add regression coverage for saving visible preview ROI definitions.
- [x] Update save behavior to persist and immediately apply current visible ROI definitions.
- [x] Verify py_compile and unittest pass.

## Expected Verification
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed
