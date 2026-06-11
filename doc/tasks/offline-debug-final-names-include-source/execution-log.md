# Execution Log

BDD: Debug final before/after filenames include selected source frame names -> Given OFFLINE debug saving is enabled and before/after frames are selected from the buffered frame list, When debug artifacts are written to `offline_tmp_frames`, Then the final before and after image filenames include the matching buffered frame filename stem after `final_before_` and `final_after_`.

RED: python -m unittest test_api_server.ApiServerTests.test_offline_debug_final_before_after_names_include_source_frame_name -> FAIL, final debug before/after files are still saved as final_before.png and final_after.png without the buffered source name.

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_debug_final_before_after_names_include_source_frame_name -> PASS.

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_debug_save_flushes_buffered_frames_and_jsonl test_api_server.ApiServerTests.test_offline_debug_final_before_after_names_include_source_frame_name test_api_server.ApiServerTests.test_offline_debug_save_writes_before_after_roi_images_and_meta test_api_server.ApiServerTests.test_offline_debug_disabled_does_not_create_debug_dir -> PASS.

GREEN: python -m unittest test_api_server -> PASS, 99 tests.

Status: Completed.
