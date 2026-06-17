# Offline Diff ROI2 ABD Values

## Goal

Show ROI2 after mean, ROI2 before mean, and ROI2 diff on the OFFLINE diff image using compact labels: `A` for after mean, `B` for before mean, and `D` for diff.

## Milestones

- [x] Record BDD/TDD expectation.
- [x] Add failing test for the `A/B/D` overlay line.
- [x] Implement diff overlay text update.
- [x] Run targeted and full OFFLINE test verification.

## Expected Verification

- Diff judgement text includes `A:<roi2_after_mean>,B:<roi2_before_mean>,D:<roi2_diff>`.
- Existing ROI2 threshold line remains present.
- Full `test_api_server` passes.

## Current Status

Completed.

## Completed Work

- Updated the second ROI2 diff overlay line to show `A:<after_mean>,B:<before_mean>,D:<roi2_diff>`.
- Kept the first ROI2 threshold line unchanged.
- Added regression coverage for the A/B/D text.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS.
- `python -m unittest test_api_server` -> PASS, 100 tests.

## Cleanup Keep

- doc/tasks/offline-diff-roi2-abd-values/backend-api-evidence.md
