# Execution Log

BDD: Differ image renders requested ROI and focus markers -> Given OFFLINE has before/after frames, ROI1 as the full saved frame, ROI2/ROI3 rectangles, and a focus point, When the differ image is saved, Then ROI1 is drawn in red, ROI2 in green, ROI3 in yellow, and the focus point is drawn as a purple 3 px circle on the differ image.

RED: `D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers` -> FAIL, expected reason: differ image pixel at ROI1 border remained raw diff `(20, 20, 20)` instead of red marker `(255, 0, 0)`.

GREEN: `D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers` -> PASS

GREEN: `D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.ApiServerTests.test_offline_diff_image_contains_overlay_not_raw_positive_diff test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers` -> PASS

GREEN: `D:\miniconda3\envs\py39\python.exe -m py_compile api_server.py test_api_server.py` -> PASS

GREEN: `D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.py` -> PASS

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers` -> PASS after strict marker bounds check.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; D:\miniconda3\envs\py39\python.exe -m py_compile api_server.py test_api_server.py` -> PASS after strict marker bounds check.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; D:\miniconda3\envs\py39\python.exe -m unittest test_api_server.py` -> PASS after strict marker bounds check.

GREEN: `D:\miniconda3\envs\py39\python.exe C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id offline-differ-roi-markers --mode preview` -> PASS, keep `task.md` and `execution-log.md`, delete `<none>`, blocked `<none>`.
