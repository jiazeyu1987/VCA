# Execution Log

BDD: ROI4 primary selects before/after before ROI1 fallback -> Given OFFLINE peak mode and ROI4 selector are enabled with buffered frames where ROI4 has a low-high-low sequence, When the second OFFLINE request stops the session, Then the final before/after pair uses the ROI4 selected after frame even if ROI1 boundary selection could have selected a different non-fallback after frame.

BDD: ROI1 boundary remains fallback when ROI4 has no match -> Given OFFLINE peak mode and ROI4 selector are enabled but buffered frames do not contain a ROI4 low-high-low sequence, When the second OFFLINE request stops the session, Then the session uses the ROI1 boundary before/after selection.

RED: python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after -> FAIL, ROI4 selector is skipped when ROI1 boundary already selected a non-fallback after.

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after -> PASS

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_roi4_selector_replaces_fallback_after_with_second_low_frame test_api_server.ApiServerTests.test_offline_roi4_selector_is_primary_before_roi1_boundary_after test_api_server.ApiServerTests.test_offline_roi4_selector_preserves_fallback_after_without_low_high_low_sequence test_api_server.ApiServerTests.test_roi4_selector_applies_to_all_fallback_after_methods test_api_server.ApiServerTests.test_roi4_selector_logs_skip_for_normal_after_method test_api_server.ApiServerTests.test_offline_peak_selection_uses_second_before_and_second_after_for_roi2 test_api_server.ApiServerTests.test_offline_peak_selection_falls_back_to_last_frame_when_second_after_boundary_frame_is_missing -> PASS

GREEN: python -m unittest test_api_server -> PASS, 98 tests.

Status: Completed.
