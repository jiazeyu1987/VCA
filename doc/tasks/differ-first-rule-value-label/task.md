# Differ First Rule Value Label

## Goal

Change the first differ-image red/green judgement line from only `OK` / `FAIL` to an `X/Y` value display where:

- `X` is the actual final judgement value.
- `Y` is the value that means the judgement succeeds.

For the final red/green result, `X/Y` is rendered as `<actual color>/green`.

## Milestones

1. Completed: Identified the current four-line differ judgement overlay in `resource/pywrapper/api_server.py`.
2. Completed: Added a failing test for the first-line `X/Y` label.
3. Completed: Implemented the first-line label change.
4. Completed: Ran targeted and full relevant tests.
5. Completed: Ran task closeout cleanup preview and marked completed.

## Expected Verification

- A unit test proves the first differ judgement label uses `<actual>/green` instead of `OK` / `FAIL`.
- Existing differ overlay tests still pass.
- `test_api_server.py` passes.
- Python compile check passes.
- Task closeout cleanup preview has no blockers.

## Current Status

Completed.

## Verification Evidence

- `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS
- `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.ApiServerTests.test_offline_diff_image_contains_overlay_not_raw_positive_diff test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS
- `$env:PYTHONDONTWRITEBYTECODE='1'; python -m py_compile api_server.py test_api_server.py` -> PASS
- `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.py` -> PASS, 64 tests
- `python C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id differ-first-rule-value-label --mode preview` -> PASS, no delete candidates, no blockers.
