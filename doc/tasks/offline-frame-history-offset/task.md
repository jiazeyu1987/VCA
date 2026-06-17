# Offline Frame History Offset

## Goal

Make OFFLINE use a configurable historical device frame instead of the newest device frame. The offset is configured in `settings` and defaults to 3 frames.

## Milestones

- [x] Record BDD/TDD expectations.
- [x] Add failing tests for frame history offset and config parsing.
- [x] Implement frame history buffering and configured offset wiring.
- [x] Run targeted and full test verification.

## Expected Verification

- `MobileCommEngine.get_latest_frame()` returns the frame from X frames before the newest when enough history exists.
- The frame history offset defaults to 3 and can be set from `settings.offline_frame_history_offset`.
- Full `test_api_server` passes.

## Current Status

Completed.

## Completed Work

- Added `offline_frame_history_offset` with default 3.
- Made the device frame engine retain a small history buffer and return the configured historical frame.
- Wired the configured offset through OFFLINE startup and provider initialization.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_parse_offline_config_defaults_focus_y_offset_to_one_mm test_api_server.ApiServerTests.test_parse_offline_config_reads_frame_history_offset test_api_server.ApiServerTests.test_mobile_comm_engine_returns_configured_history_frame` -> PASS.
- `python -m unittest test_api_server` -> PASS, 102 tests.

## Cleanup Keep

- doc/tasks/offline-frame-history-offset/backend-api-evidence.md
