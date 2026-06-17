# Backend API Evidence

## Scope

- Handler/service: OFFLINE final diff rendering in `resource/pywrapper/api_server.py`.
- API contract: OFFLINE response shape and file paths remain unchanged.
- Data contract: generated diff image content changes to ROI2-only overlay.

## Auth, Permissions, Validation, And Error Behavior

- No auth or permission changes.
- No validation behavior changes.
- No persistence schema changes.

## Required Config, Services, Fixtures, And Migrations

- Config: existing OFFLINE image output settings.
- Services: none for unit tests.
- Fixtures: in-memory frames in `test_api_server.py`.
- Migrations: none.

## BDD Scenarios

BDD: Diff overlay text only shows ROI2 -> Given OFFLINE has computed ROI2 metrics, When the diff image judgement lines are built, Then only the two ROI2 lines are returned.

BDD: Diff overlay markers only show ROI2 -> Given OFFLINE has ROI1, ROI2, ROI3, and focus marker data, When the diff image is rendered, Then only the ROI2 rectangle and focus marker/guides are drawn on the diff image.

## RED Command

RED: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_offline_diff_image_does_not_draw_roi4_marker` -> FAIL, diff overlay still includes ROI3/ROI4 text and ROI1/ROI4 marker rectangles.

## GREEN Command

GREEN: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_offline_diff_image_does_not_draw_roi4_marker` -> PASS.

GREEN: `python -m unittest test_api_server` -> PASS, 100 tests.

## Contract Or Integration Verification

OFFLINE response shape and output file paths are unchanged. Diff image content now contains only ROI2 judgement text and ROI2 marker rectangle.

## Observability Touchpoints

- No log schema changes.
- Diff image output content is verified by pixel tests.

## Blockers And Downstream Skill Needs

- None.
