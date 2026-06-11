# Backend API Evidence

## Scope

- Handler/service: `OfflineSessionManager` in `resource/pywrapper/api_server.py`.
- API contract: OFFLINE request and response field names remain unchanged.
- Data contract: `roi2_color` and `treatment_ok` now reflect only ROI2 threshold classification.

## Auth, Permissions, Validation, And Error Behavior

- No auth or permission changes.
- Existing OFFLINE request validation remains unchanged.
- Positive focus Y offset still requires provider depth and fails fast when depth is missing or invalid.

## Required Config, Services, Fixtures, And Migrations

- Config: existing `settings.focus_guides.y_offset_mm`.
- Services: none for unit tests.
- Fixtures: in-memory frame sequences in `test_api_server.py`.
- Migrations: none.

## BDD Scenarios

BDD: ROI2 is the only green classification rule -> Given ROI2 difference is below threshold and ROI3 metrics satisfy the old override thresholds, When OFFLINE finalizes, Then the result remains red and no ROI3 override is applied.

BDD: ROI2 follows configured focus Y offset -> Given a valid focus point, provider depth, and positive `focus_guides.y_offset_mm`, When OFFLINE initializes ROI regions, Then ROI2 is computed from the offset focus anchor instead of the raw focus point.

## RED Command

RED: `python -m unittest test_api_server.ApiServerTests.test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green test_api_server.ApiServerTests.test_offline_roi2_rect_uses_focus_y_offset` -> FAIL, ROI3 still flips red to green and ROI2 still uses the raw focus anchor.

## GREEN Command

GREEN: `python -m unittest test_api_server.ApiServerTests.test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green test_api_server.ApiServerTests.test_offline_roi2_rect_uses_focus_y_offset` -> PASS.

GREEN: `python -m unittest test_api_server` -> PASS, 100 tests.

## Contract Or Integration Verification

The OFFLINE API response shape is unchanged. `roi2_color` and `treatment_ok` now represent ROI2-only classification, and `roi2_rect` reflects the focus Y offset.

## Observability Touchpoints

- Existing `focus_roi_initialized` diagnostic should report the offset ROI rect.
- Existing `stop_decision` diagnostic should report ROI2-only color and metrics.

## Blockers And Downstream Skill Needs

- None.
