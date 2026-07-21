# Execution Log: Algorithm Screenshot Test Data Sequence

2026-07-21

- BDD: test-data frame sequence -> Given an OFFLINE request has `save_test_data_frames=true`, When frames are captured, Then each captured frame is saved in order under `test_data_output_dir\<yyyyMMddHHmmss>\001.png`, `002.png`, `003.png`.
- BDD: normal treatment isolation -> Given `save_test_data_frames` is absent or false, When treatment OFFLINE runs, Then no `test_data` frame sequence is created.
- BDD: screenshot mode skips treatment judgement -> Given `offline_peak` is enabled and a pure screenshot sequence has no valid treatment peak, When `save_test_data_frames=true`, Then the OFFLINE stop response succeeds as capture-only and reports the test-data directory/count.
- RED: `python -m unittest test_api_server.ApiServerTests.test_offline_save_test_data_frames_writes_timestamped_png_sequence` in a temporary clean HEAD copy with the updated test file -> FAIL, expected reason: `OfflineConfig` had no `test_data_output_dir`/test-data frame writer support.
- GREEN: `python -m unittest test_api_server.ApiServerTests.test_offline_save_test_data_frames_writes_timestamped_png_sequence` -> PASS.
- GREEN: `python -m unittest test_api_server.ApiServerTests.test_parse_offline_config_reads_roi_and_debug_settings test_api_server.ApiServerTests.test_offline_save_test_data_frames_writes_timestamped_png_sequence test_api_server.ApiServerTests.test_offline_switch_waits_for_previous_capture_done_before_new_start test_api_server.ApiServerTests.test_offline_output_logs_flush_and_output_paths test_api_server.ApiServerTests.test_offline_green_save_logs_main_program_state_sync` -> PASS.
- GREEN: `python -m py_compile resource\pywrapper\api_server.py resource\pywrapper\test_api_server.py` -> PASS.
