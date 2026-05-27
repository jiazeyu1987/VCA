# Offline Differ ROI Markers

## Goal

When OFFLINE saves differ images under the configured image output directory (for example `D:/software_data/img`), render ROI1, ROI2, ROI3, and the focus point directly on the differ image:

- ROI1: red rectangle
- ROI2: green rectangle
- ROI3: yellow rectangle
- Focus point: purple 3 px circular marker

## Milestones

1. Completed: Identified the differ-image generation and save path in `resource/pywrapper/api_server.py`.
2. Completed: Added a failing behavior test for differ-image ROI/focus markers.
3. Completed: Implemented marker rendering in the existing differ-image pipeline.
4. Completed: Ran targeted verification and recorded evidence.
5. Completed: Ran task closeout cleanup preview and marked the task completed.

## Expected Verification

- Targeted unittest proving the differ image contains the requested ROI/focus marker colors.
- Existing relevant diff-image unittest remains passing.
- Python compile check for touched Python files.
- Task closeout cleanup preview.

## Current Status

Completed.

## Verification Evidence

- `$env:PYTHONDONTWRITEBYTECODE='1'; D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers` -> PASS
- `D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.ApiServerTests.test_offline_diff_image_contains_overlay_not_raw_positive_diff test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers` -> PASS
- `$env:PYTHONDONTWRITEBYTECODE='1'; D:\miniconda3\envs\py39\python.exe -m py_compile api_server.py test_api_server.py` -> PASS
- `$env:PYTHONDONTWRITEBYTECODE='1'; D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.py` -> PASS
- `D:\miniconda3\envs\py39\python.exe C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id offline-differ-roi-markers --mode preview` -> PASS, no delete candidates, no blockers.
