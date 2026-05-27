# Execution Log

BDD: First differ judgement displays actual/success value -> Given the differ overlay renders four red/green judgement lines, When the final judgement is red or green, Then the first line displays `<actual>/green` instead of only `OK` or `FAIL`.

RED: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> FAIL, expected reason: `api_server.build_diff_overlay_judgement_lines` does not exist yet and first line is still built inline as `OK` / `FAIL`.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.ApiServerTests.test_offline_diff_image_contains_overlay_not_raw_positive_diff test_api_server.ApiServerTests.test_offline_diff_image_draws_roi_and_focus_markers test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m py_compile api_server.py test_api_server.py` -> PASS.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.py` -> PASS, 64 tests.

GREEN: `python C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id differ-first-rule-value-label --mode preview` -> PASS, keep `task.md` and `execution-log.md`, delete `<none>`, blocked `<none>`.
