# Offline Debug Final Names Include Source

## Goal

When OFFLINE debug artifacts are saved under `offline_tmp_frames`, include the selected buffered source frame name in the final before/after image filenames.

## Milestones

- [x] Add BDD/TDD coverage for final before/after source-aware filenames.
- [x] Implement source-aware debug final before/after filenames.
- [x] Run targeted OFFLINE debug tests.
- [x] Record final verification and status.

## Expected Verification

- `final_before_<source-buffered-name>.png` and `final_after_<source-buffered-name>.png` are saved in the debug directory.
- Existing debug ROI crop files remain available.
- BDD, RED, and GREEN evidence are recorded in `execution-log.md`.

## Current Status

Completed.

## Completed Work

- Added source-aware final debug image names under each OFFLINE debug directory.
- Kept legacy `final_before.png` and `final_after.png` outputs for existing consumers.
- Added a regression test for `final_before_<source>.png` and `final_after_<source>.png`.

## Final Verification

- `python -m unittest test_api_server.ApiServerTests.test_offline_debug_final_before_after_names_include_source_frame_name` -> PASS.
- `python -m unittest test_api_server.ApiServerTests.test_offline_debug_save_flushes_buffered_frames_and_jsonl test_api_server.ApiServerTests.test_offline_debug_final_before_after_names_include_source_frame_name test_api_server.ApiServerTests.test_offline_debug_save_writes_before_after_roi_images_and_meta test_api_server.ApiServerTests.test_offline_debug_disabled_does_not_create_debug_dir` -> PASS.
- `python -m unittest test_api_server.ApiServerTests.test_offline_peak_failure_still_saves_img_and_tmp_artifacts test_api_server.ApiServerTests.test_offline_db_update_failure_still_saves_debug_artifacts test_api_server.ApiServerTests.test_offline_debug_final_before_after_names_include_source_frame_name` -> PASS.
- `python -m unittest test_api_server` -> PASS, 99 tests.
