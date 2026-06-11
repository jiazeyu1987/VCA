# Execution Log

BDD: ROI2 is the only green classification rule -> Given ROI2 difference is below threshold and ROI3 metrics satisfy the old override thresholds, When OFFLINE finalizes, Then the result remains red and no ROI3 override is applied.

BDD: ROI2 follows configured focus Y offset -> Given a valid focus point, provider depth, and positive `focus_guides.y_offset_mm`, When OFFLINE initializes ROI regions, Then ROI2 is computed from the offset focus anchor instead of the raw focus point.

RED: python -m unittest test_api_server.ApiServerTests.test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green test_api_server.ApiServerTests.test_offline_roi2_rect_uses_focus_y_offset -> FAIL, ROI3 still flips red to green and ROI2 still uses the raw focus anchor.

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_roi3_g1_g2_metrics_do_not_flip_red_to_green test_api_server.ApiServerTests.test_offline_roi2_rect_uses_focus_y_offset -> PASS.

GREEN: python -m unittest test_api_server -> PASS, 100 tests.

Status: Completed.
