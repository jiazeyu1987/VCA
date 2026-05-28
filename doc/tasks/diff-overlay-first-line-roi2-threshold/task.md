# Diff Overlay First Line ROI2 Threshold

## Goal

Change the diff image overlay first judgement line from final color text to an ROI2 numeric comparison showing the current ROI2 diff against the configured judgement threshold.

## Milestones

- [x] Create task documentation and BDD baseline.
- [x] Update the focused overlay test first and capture RED evidence.
- [x] Implement the first-line ROI2 comparison behavior.
- [x] Run focused and relevant regression verification.
- [x] Close out cleanup preview and commit only task-owned changes.

## Expected Verification

- `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` from `D:\ocr3\resource\pywrapper`
- `python -m unittest test_api_server.py` from `D:\ocr3\resource\pywrapper`
- `python C:/Users/BJB110/.codex/skills/backend-api-delivery/scripts/validate_backend_api.py --evidence doc/tasks/diff-overlay-first-line-roi2-threshold/backend-api-evidence.md`
- `python C:/Users/BJB110/.codex/skills/task-closeout-cleanup/scripts/task_closeout.py --task-id diff-overlay-first-line-roi2-threshold --mode preview`

## Current Status

Completed. Diff overlay first line now shows ROI2 current/threshold numeric judgement, and verification passed.

## Completed Work

- Created this task record.
- Recorded initial BDD scenario in `execution-log.md`.
- Updated the focused overlay test to expect the ROI2 numeric first line.
- Updated `build_diff_overlay_judgement_lines()` so the first line uses ROI2 current/threshold text and ROI2 threshold pass state.

## Verification Evidence

- RED: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` from `D:\ocr3\resource\pywrapper` -> FAIL, expected reason: first line is still `1. Result: red/green`.
- GREEN: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` from `D:\ocr3\resource\pywrapper` -> PASS.
- GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.py` from `D:\ocr3\resource\pywrapper` -> PASS, 64 tests.
- GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m py_compile api_server.py test_api_server.py` from `D:\ocr3\resource\pywrapper` -> PASS.
- GREEN: `python C:\Users\BJB110\.codex\skills\backend-api-delivery\scripts\validate_backend_api.py --evidence doc\tasks\diff-overlay-first-line-roi2-threshold\backend-api-evidence.md` from `D:\ocr3` -> PASS.
- Cleanup preview: `python C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id diff-overlay-first-line-roi2-threshold --mode preview` from `D:\ocr3` -> PASS, status ready, no blocked paths or warnings.
- Cleanup apply: `python C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id diff-overlay-first-line-roi2-threshold --mode apply` from `D:\ocr3` -> PASS, deleted task-closeout-owned `backend-api-evidence.md`.

## Remaining Blockers

- None.
