# Offline ROI4 Primary ROI1 Fallback

## Goal

Change OFFLINE before/after frame selection so ROI4 low-high-low after selection is the primary selection method, and ROI1 boundary selection is used only as the explicit fallback when ROI4 cannot select a matching after frame.

## Milestones

- [x] Document expected behavior and verification.
- [x] Add a failing regression test for ROI4-primary selection.
- [x] Implement ROI4-primary / ROI1-fallback selection without changing the red/green threshold logic.
- [x] Run targeted OFFLINE tests and record evidence.

## Expected Verification

- BDD scenario and RED/GREEN commands recorded in `execution-log.md`.
- Targeted unit tests prove ROI4 can select the primary after even when ROI1 would have selected a different normal boundary after.
- Existing ROI1 fallback behavior remains covered when ROI4 has no low-high-low match.
- Backend evidence recorded in `backend-api-evidence.md`.

## Current Status

Completed.

## Completed Work

- Added a regression test proving ROI4 can select the primary `after` frame before ROI1 boundary fallback.
- Updated `OfflineSessionManager._apply_roi4_after_selector_if_needed` so it can run in primary mode without requiring an existing fallback `after_method`.
- Updated OFFLINE finalization order so ROI4 primary selection runs before ROI1 boundary selection; ROI1 boundary selection runs only when ROI4 does not select an after frame.
- Kept red/green ROI2/ROI3 threshold logic unchanged.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after` -> PASS.
- `python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_replaces_fallback_after_with_second_low_frame test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after test_api_server.ApiServerTests.test_offline_roi4_selector_preserves_fallback_after_without_low_high_low_sequence test_api_server.ApiServerTests.test_roi4_selector_applies_to_all_fallback_after_methods test_api_server.ApiServerTests.test_roi4_selector_logs_skip_for_normal_after_method test_api_server.ApiServerTests.test_offline_peak_selection_uses_second_before_and_second_after_for_roi2 test_api_server.ApiServerTests.test_offline_peak_selection_falls_back_to_last_frame_when_second_after_boundary_frame_is_missing` -> PASS.
- `python -m unittest test_api_server` -> PASS, 98 tests.

## Cleanup Keep

- doc/tasks/offline-roi4-primary-roi1-fallback/backend-api-evidence.md
