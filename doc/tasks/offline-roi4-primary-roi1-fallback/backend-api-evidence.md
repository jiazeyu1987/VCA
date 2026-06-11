# Backend API Evidence

## Scope

- Handler/service: `OfflineSessionManager` in `resource/pywrapper/api_server.py`.
- API contract: OFFLINE start/stop request and response shape remain unchanged.
- Data contract: response fields such as `roi2_color`, `before_seq`, `after_seq`, `after_method`, and ROI4 diagnostics remain unchanged.

## Auth, Permissions, Validation, And Error Behavior

- No auth or permission changes.
- Existing OFFLINE request validation remains unchanged.
- ROI4 configuration validation remains fail-fast; invalid ROI4 configuration is not downgraded to ROI1 fallback.

## Required Config, Services, Fixtures, And Migrations

- Required config: `settings.peak_detect.roi4_after_selector`, ROI4 rect or bottom region, `offline_peak`.
- Required services: none for unit tests.
- Fixtures: in-memory frame sequences in `test_api_server.py`.
- Migrations: none.

## BDD Scenarios

BDD: ROI4 primary selects before/after before ROI1 fallback -> Given OFFLINE peak mode and ROI4 selector are enabled with buffered frames where ROI4 has a low-high-low sequence, When the second OFFLINE request stops the session, Then the final before/after pair uses the ROI4 selected after frame even if ROI1 boundary selection could have selected a different non-fallback after frame.

BDD: ROI1 boundary remains fallback when ROI4 has no match -> Given OFFLINE peak mode and ROI4 selector are enabled but buffered frames do not contain a ROI4 low-high-low sequence, When the second OFFLINE request stops the session, Then the session uses the ROI1 boundary before/after selection.

## RED Command

RED: `python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after` -> FAIL, because ROI4 selector was skipped after ROI1 selected a non-fallback after.

## GREEN Command

GREEN: `python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after` -> PASS.

GREEN: `python -m unittest test_api_server` -> PASS, 98 tests.

## Contract Or Integration Verification

The OFFLINE API response contract is unchanged. Verification covered response fields for `roi4_after_selector_applied`, `roi4_after_frame_index`, `roi4_after_method`, `after_seq`, and `after_method`.

## Observability Touchpoints

- Existing OFFLINE diagnostic events show ROI4 selection or ROI1 boundary fallback.
- `roi4_after_selector_begin` now records `require_fallback_after` so logs distinguish primary selection from fallback-only selection.

## Blockers And Downstream Skill Needs

- None.
