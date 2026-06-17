# Backend API Evidence

## Scope

- Handler/service: device frame source used by OFFLINE in `resource/pywrapper/api_server.py`.
- API contract: OFFLINE request and response shape remain unchanged.
- Data contract: before/after frame source changes from newest frame to configured historical frame.

## Auth, Permissions, Validation, And Error Behavior

- No auth or permission changes.
- Config validation fails fast for invalid frame history offset.
- No persistence schema changes.

## Required Config, Services, Fixtures, And Migrations

- Config: optional `settings.offline_frame_history_offset`, default 3.
- Services: none for unit tests.
- Fixtures: in-memory frame callbacks in `test_api_server.py`.
- Migrations: none.

## BDD Scenarios

BDD: OFFLINE frame fetch uses configured historical frame -> Given the device stream has received more than X frames, When `get_latest_frame()` is called with frame history offset X, Then it returns the frame from X frames before the newest frame.

BDD: Frame history offset defaults to three -> Given settings do not define `offline_frame_history_offset`, When OFFLINE config is parsed, Then the configured frame history offset is 3.

## RED Command

RED: `python -m unittest test_api_server.ApiServerTests.test_parse_offline_config_reads_frame_history_offset test_api_server.ApiServerTests.test_parse_offline_config_defaults_focus_y_offset_to_one_mm test_api_server.ApiServerTests.test_mobile_comm_engine_returns_configured_history_frame` -> FAIL, frame history offset config and engine history buffer do not exist.

## GREEN Command

GREEN: `python -m unittest test_api_server.ApiServerTests.test_parse_offline_config_defaults_focus_y_offset_to_one_mm test_api_server.ApiServerTests.test_parse_offline_config_reads_frame_history_offset test_api_server.ApiServerTests.test_mobile_comm_engine_returns_configured_history_frame` -> PASS.

GREEN: `python -m unittest test_api_server` -> PASS, 102 tests.

## Contract Or Integration Verification

OFFLINE request/response shape and file paths remain unchanged. The device frame source now returns a configured historical frame instead of always returning the newest frame.

## Observability Touchpoints

- Config load log records `offline_frame_history_offset`.

## Blockers And Downstream Skill Needs

- None.
