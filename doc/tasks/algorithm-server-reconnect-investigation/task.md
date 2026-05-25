# Task: Algorithm Server Reconnect Investigation

## Goal
Identify why the main program no longer automatically reconnects after the algorithm server disconnects.

## Milestones
- [completed] M1: Locate connection, disconnect detection, and reconnect ownership.
- [completed] M2: Compare current behavior against recent changes and tests.
- [completed] M3: Record root cause, impact, verification evidence, and recommended fix scope.

## Expected Verification
- Inspect code paths that create and maintain the algorithm server connection.
- Inspect tests or scripts that cover disconnect and reconnect behavior.
- If a deterministic local reproduction is possible without missing prerequisites, run it and record evidence.

## Current Status
Completed.

## Completed Work
- Located the current algorithm server implementation in `D:\ocr3\resource\pywrapper\api_server.py`.
- Verified the server-side device reconnect path still exists in `PyMobileCommProvider.fetch_online()`: disconnected device state calls `RestartAdbServer()` and `Auto_Initialize()` before fetching provider data.
- Located the main-program reconnect owner in `D:\ProjectPackage\Vein\sqw\Vein\GLPyModule\JExtension\VeinTreat\VeinTreat.py` and `D:\ProjectPackage\Vein\sqw\Vein\bin\Python\slicer\util.py`.
- Compared history and found commit `8033212e` (`2026-04-03`, "改成短链接") changed online requests to request-scoped short connections, enabled `_algorithm_online_simple_mode = True`, disabled prewarm/reconnect/keepalive branches, and passed `restart_process_on_error=False` for request-scoped online requests.
- Found `PAAA.start_process_if_needed()` logs `port_ready` but only uses `process_running` to decide whether to start the server, so an existing but non-listening/hung `ocrapp_pureray.exe` process is treated as healthy.
- Ran the existing server reconnect unit tests as a control check.

## Blockers
- No live `ocrapp_pureray` process, no 30415 listener, and no current `OCRSERVER\ocrlog\pywrapper_api_server.log` were present on this machine during the investigation, so no real runtime disconnect reproduction was possible.

## Final Verification
- `python -m unittest -k reconnect test_api_server.ApiServerTests` from `D:\ocr3\resource\pywrapper` -> PASS, 5 tests.
- Static inspection completed for current main-program reconnect code and the relevant historical commits.
