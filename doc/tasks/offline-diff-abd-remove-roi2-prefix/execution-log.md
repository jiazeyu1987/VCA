# Execution Log

BDD: Diff A/B/D line omits redundant ROI2 prefix -> Given the diff overlay only displays ROI2 metrics, When ROI2 A/B/D values are rendered, Then the second line is `2. A:<after>,B:<before>,D:<diff>`.

RED: python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value -> FAIL, line 2 still includes `ROI2:`.

GREEN: python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value -> PASS.

GREEN: python -m unittest test_api_server -> PASS, 100 tests.

Status: Completed.
