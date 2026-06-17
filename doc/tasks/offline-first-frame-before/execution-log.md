# Execution Log

BDD: ROI1 boundary keeps first before -> Given OFFLINE peak mode captures a first frame and later detects a ROI1 active interval, When stop processing selects boundary frames, Then the final before remains the first captured frame and after is selected by the ROI1 boundary.

RED: python -m unittest test_api_server.ApiServerTests.test_offline_peak_logs_threshold_and_after_selection -> FAIL, ROI1 boundary still emits before_selected.

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_peak_logs_threshold_and_after_selection -> PASS.

GREEN: python -m unittest test_api_server -> PASS.

Status: Completed.
