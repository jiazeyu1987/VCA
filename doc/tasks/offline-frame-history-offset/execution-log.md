# Execution Log

BDD: OFFLINE frame fetch uses configured historical frame -> Given the device stream has received more than X frames, When `get_latest_frame()` is called with frame history offset X, Then it returns the frame from X frames before the newest frame.

BDD: Frame history offset defaults to three -> Given settings do not define `offline_frame_history_offset`, When OFFLINE config is parsed, Then the configured frame history offset is 3.

RED: python -m unittest test_api_server.ApiServerTests.test_parse_offline_config_reads_frame_history_offset test_api_server.ApiServerTests.test_parse_offline_config_defaults_focus_y_offset_to_one_mm test_api_server.ApiServerTests.test_mobile_comm_engine_returns_configured_history_frame -> FAIL, frame history offset config and engine history buffer do not exist.

RED: python -m unittest test_api_server.ApiServerTests.test_mobile_comm_engine_returns_configured_history_frame -> FAIL, engine history lookup is not returning the configured historical frame yet.

GREEN: python -m unittest test_api_server.ApiServerTests.test_parse_offline_config_defaults_focus_y_offset_to_one_mm test_api_server.ApiServerTests.test_parse_offline_config_reads_frame_history_offset test_api_server.ApiServerTests.test_mobile_comm_engine_returns_configured_history_frame -> PASS.

GREEN: python -m unittest test_api_server -> PASS, 102 tests.

Status: Completed.
