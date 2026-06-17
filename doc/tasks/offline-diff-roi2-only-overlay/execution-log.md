# Execution Log

BDD: Diff overlay text only shows ROI2 -> Given OFFLINE has computed ROI2 metrics, When the diff image judgement lines are built, Then only the two ROI2 lines are returned.

BDD: Diff overlay markers only show ROI2 -> Given OFFLINE has ROI1, ROI2, ROI3, and focus marker data, When the diff image is rendered, Then only the ROI2 rectangle and focus marker/guides are drawn on the diff image.

RED: python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_offline_diff_image_does_not_draw_roi4_marker -> FAIL, diff overlay still includes ROI3/ROI4 text and ROI1/ROI4 marker rectangles.

GREEN: python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_offline_diff_image_does_not_draw_roi4_marker -> PASS.

GREEN: python -m unittest test_api_server -> PASS, 100 tests.

Status: Completed.
