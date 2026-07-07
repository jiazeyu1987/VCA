# Execution Log

## BDD Scenarios
- BDD: Save current visible ROI -> Given ROI input boxes are blank but ROI overlays are visible in preview, When the user clicks save, Then settings store the preview ROI positions and shapes.
- BDD: Saved ROI does not drift after focus changes -> Given saved rectangle and ellipse ROI definitions, When the focus point changes and preview refreshes, Then each saved ROI center remains unchanged.
- BDD: Save applies immediately in current session -> Given preview-derived ROI definitions, When save is clicked, Then ROI input fields are filled with the saved X/Y/width/height values so the current GUI state is locked.

## TDD Evidence
- RED: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> FAIL, missing preview-to-definition helper and missing GUI save-field application coverage.
- GREEN: `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS.
- GREEN: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS, 33 tests.
