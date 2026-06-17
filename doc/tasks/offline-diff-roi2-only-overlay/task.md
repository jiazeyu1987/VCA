# Offline Diff ROI2 Only Overlay

## Goal

Make OFFLINE diff images display only ROI2 judgement text and the ROI2 marker rectangle. Remove ROI1, ROI3, and ROI4 diagnostic text and non-ROI2 marker rectangles from the diff image.

## Milestones

- [x] Record BDD/TDD expectations.
- [x] Add failing tests for ROI2-only diff text and markers.
- [x] Implement ROI2-only diff overlay rendering.
- [x] Run targeted and full OFFLINE test verification.

## Expected Verification

- Diff overlay text contains only two ROI2 lines.
- Diff image draws the ROI2 rectangle and focus marker/guides.
- Diff image no longer draws ROI1 full-frame, ROI3, or ROI4 rectangles.

## Current Status

Completed.

## Completed Work

- Reduced diff judgement overlay text to two ROI2 lines.
- Removed ROI1 full-frame, ROI3, and ROI4 marker rectangles from diff images.
- Kept ROI2 rectangle and focus marker/guides on diff images.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_offline_diff_image_does_not_draw_roi4_marker` -> PASS.
- `python -m unittest test_api_server` -> PASS, 100 tests.

## Cleanup Keep

- doc/tasks/offline-diff-roi2-only-overlay/backend-api-evidence.md
