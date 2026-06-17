# Offline Diff ABD Remove ROI2 Prefix

## Goal

Remove the redundant `ROI2:` prefix from the A/B/D value line on OFFLINE diff images because the diff overlay now only displays ROI2 metrics.

## Milestones

- [x] Record BDD/TDD expectation.
- [x] Add failing test for the simplified A/B/D line.
- [x] Implement the diff overlay text update.
- [x] Run targeted and full OFFLINE test verification.

## Expected Verification

- Diff line 2 is formatted as `2. A:<after>,B:<before>,D:<diff>`.
- Full `test_api_server` passes.

## Current Status

Completed.

## Completed Work

- Removed `ROI2:` from the A/B/D value line.
- Kept the first threshold line unchanged.
- Updated regression coverage.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS.
- `python -m unittest test_api_server` -> PASS, 100 tests.

## Cleanup Keep

- doc/tasks/offline-diff-abd-remove-roi2-prefix/backend-api-evidence.md
