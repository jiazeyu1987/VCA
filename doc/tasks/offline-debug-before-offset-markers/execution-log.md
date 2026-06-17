# Execution Log

BDD: Debug flush marks selected before and before plus offset frames -> Given OFFLINE debug saving is enabled and buffered frames include the selected before frame and the frame at before index plus `frame_history_offset`, When debug frames are flushed, Then marker image files are written for both frames.

RED: python -m unittest test_api_server.ApiServerTests.test_offline_debug_save_flushes_buffered_frames_and_jsonl -> FAIL, before marker files are not written.

GREEN: python -m unittest test_api_server.ApiServerTests.test_offline_debug_save_flushes_buffered_frames_and_jsonl -> PASS.

Status: In progress.
