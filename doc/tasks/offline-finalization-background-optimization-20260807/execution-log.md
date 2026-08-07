# Execution Log: Offline Finalization Background Optimization

2026-08-07

- BDD: next treatment starts during previous persistence -> Given a completed treatment is saving debug frames and finalizing its session package, When the client starts the next treatment with `wait_before_capture=true`, Then the next treatment captures its before frame without waiting for the previous persistence to finish.
- BDD: persistence remains complete -> Given a treatment is allowed to finalize outside the next treatment's critical path, When background persistence completes, Then its debug frames, final outputs, result flag, database update, and session package are preserved.
- BDD: persistence failure remains explicit -> Given background persistence fails, When completion is observed through logs or shutdown draining, Then the failure is recorded explicitly and is not reported as successful persistence.
- BDD: treatment behavior remains unchanged -> Given either supported hardware frame cadence, When treatment frames are captured and stopped, Then boundary detection and treatment result calculation use the complete live frame stream.
- BDD: disabled session recording preserves OFFLINE treatment -> Given `SessionRecorderConfig(enabled=False)` is injected into the OFFLINE manager, When a real treatment start and stop path completes, Then capture succeeds and no recording package is created.
- RED: `python -m unittest test_api_server.ApiServerTests.test_offline_next_treatment_captures_before_frame_while_previous_finalization_is_blocked test_session_recorder.SessionRecorderTests.test_stopping_session_can_finalize_while_next_session_records` from `resource\pywrapper` -> FAIL, expected reasons: the next start waits on the manager lock until previous finalization completes, and `SessionDataRecorder.record_frame` has no explicit `session_id` routing.
- RED: `python -m unittest test_api_server.ApiServerTests.test_offline_close_drains_active_and_detached_sessions test_api_server.ApiServerTests.test_offline_close_reports_background_persistence_failure` from `resource\pywrapper` -> FAIL, expected reason: `OfflineSessionManager` has no shutdown drain API.
- RED: `python -m unittest test_api_server.ApiServerTests.test_offline_close_reports_background_persistence_failure` from `resource\pywrapper` -> FAIL, expected reason: shutdown draining omitted an already-finished failure that remained in the active slot.
- RED: `python -m unittest test_api_server.ApiServerTests.test_offline_close_rejects_new_treatment_starts` from `resource\pywrapper` -> FAIL, expected reason: shutdown draining did not close the manager to racing client starts.
- RED: `python -m unittest test_api_server.ApiServerTests.test_offline_manager_succeeds_without_package_when_session_recording_disabled` from `resource\pywrapper` -> FAIL, expected reason: the disabled recorder returns no session ID and the OFFLINE start path raises `RuntimeError: session recorder did not return a session_id`.
- GREEN: `python -m unittest test_api_server.ApiServerTests.test_offline_manager_succeeds_without_package_when_session_recording_disabled` from `resource\pywrapper` -> PASS (1 test); disabled recording completes the real OFFLINE start/stop path without creating a package.
- GREEN: `python -m unittest test_session_recorder test_api_server` from `resource\pywrapper` -> PASS (129 tests).
- GREEN: `python -m py_compile api_server.py session_recorder.py test_api_server.py test_session_recorder.py` from `resource\pywrapper` -> PASS.
- GREEN: `python -B -m unittest test_session_recorder test_api_server` from `resource\pywrapper` -> PASS (129 tests) after independent review and experience consolidation.
- GREEN: `python -B -m unittest test_server_scripts test_offline_screenshot_probe` from `resource\pywrapper` -> PASS (28 tests).
- GREEN: `git diff --check -- <task-owned source, tests, and system docs>` -> PASS with only expected LF-to-CRLF warnings.
- CLOSEOUT: `task_closeout.py --mode preview` matched the intended task scope; apply removed only the task review run and intermediate evidence while retaining task, execution, verification, production, and formal test files.
