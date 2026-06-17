# Execution Log

BDD: Diff overlay shows ROI2 after before and diff values -> Given OFFLINE has computed ROI2 before mean, after mean, and diff, When diff overlay judgement lines are built, Then the overlay includes `A:<after>,B:<before>,D:<diff>`.

RED: python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value -> FAIL, second ROI2 line still shows diff/threshold instead of A/B/D values.

GREEN: python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value -> PASS.

GREEN: python -m unittest test_api_server -> PASS, 100 tests.

Status: Completed.
