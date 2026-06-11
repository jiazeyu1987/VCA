# Offline ROI2 Only Offset

## Goal

Keep OFFLINE red/green treatment classification based only on the ROI2 grayscale-difference rule, and make ROI2/ROI3 region initialization use the configured focus Y offset so ROI2 moves with the offset focus point.

## Milestones

- [x] Record BDD/TDD expectations.
- [x] Add failing tests for ROI3 no-longer-overrides and ROI2 offset movement.
- [x] Remove ROI3 green override from final classification.
- [x] Apply focus Y offset to ROI region initialization.
- [x] Run targeted and full OFFLINE test verification.

## Expected Verification

- ROI2 red remains red even when ROI3 metrics would previously flip it green.
- ROI2 rect moves by `focus_guides.y_offset_mm * image_height / provider_depth`.
- Existing OFFLINE tests pass after updating expectations for ROI2-only behavior.

## Current Status

Completed.

## Completed Work

- Removed ROI3 override execution from final OFFLINE red/green classification.
- Added ROI2-only regression coverage proving ROI3 metrics no longer flip a red ROI2 result to green.
- Applied `focus_guides.y_offset_mm` to ROI region initialization using the same provider-depth conversion as focus guide rendering.
- Updated ROI marker rendering expectations so ROI2/ROI3 markers reflect the offset ROI anchor.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green test_api_server.ApiServerTests.test_offline_roi2_rect_uses_focus_y_offset` -> PASS.
- `python -m unittest test_api_server.ApiServerTests.test_offline_two_signal_session_returns_green_roi2_result test_api_server.ApiServerTests.test_offline_two_signal_session_returns_red_roi2_result test_api_server.ApiServerTests.test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green test_api_server.ApiServerTests.test_offline_roi2_rect_uses_focus_y_offset test_api_server.ApiServerTests.test_focus_overlay_uses_configured_mm_offset_without_moving_roi_anchor test_api_server.ApiServerTests.test_offline_debug_save_writes_before_after_roi_images_and_meta` -> PASS.
- `python -m unittest test_api_server` -> PASS, 100 tests.

## Cleanup Keep

- doc/tasks/offline-roi2-only-offset/backend-api-evidence.md
