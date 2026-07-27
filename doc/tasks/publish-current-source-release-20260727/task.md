# Publish Current Source Release 20260727

## Goal
Commit the current confirmed source changes, push the source branch, run `publish_release.bat`, and push the release result again.

## Milestones
- [x] Confirm release path and dirty working-tree scope.
- [x] Run focused source verification before commit.
- [x] Commit task-related source changes and push the source branch.
- [ ] Run `publish_release.bat` to package and publish OCRSERVER.
- [ ] Run final source/release git checks and record closeout evidence.

## Expected Verification
- `python -B -m unittest tools.test_image_annotation_exporter tools.test_session_timeline_analyzer` passes.
- `python -B -m unittest test_api_server.ApiServerTests.test_offline_output_logs_flush_and_output_paths test_api_server.ApiServerTests.test_offline_save_test_data_frames_writes_timestamped_png_sequence` passes from `resource\pywrapper`.
- `python -B -m py_compile` passes for changed Python files.
- `git diff --check` passes for changed text files.
- `publish_release.bat` completes or fails fast with a concrete blocker.

## Current Status
blocked_missing_release_python

## Remaining Blocker
- `publish_release.bat` requires `D:\miniconda3\envs\houyang\python.exe` through `tools\package_pywrapper_server.ps1` and `tools\package_session_timeline_analyzer.ps1`; that executable is missing on this machine, so publishing must stop instead of silently switching Python runtimes.
