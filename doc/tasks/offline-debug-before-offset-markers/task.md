# Offline Debug Before Offset Markers

## Goal

When OFFLINE debug frames are flushed to `offline_tmp_frames`, create explicit marker image files for the selected before frame and the selected before frame plus the configured frame history offset.

## Milestones

- [x] Record BDD/TDD expectations.
- [x] Add failing test for before and before-plus-offset marker files.
- [x] Implement marker file output in debug flush.
- [x] Run targeted and full test verification.

## Expected Verification

- Debug directory includes `selected_before_<source>.png`.
- Debug directory includes `selected_before_plus_offset_<source>.png` when that frame exists.
- Full `test_api_server` passes.

## Current Status

Completed.
