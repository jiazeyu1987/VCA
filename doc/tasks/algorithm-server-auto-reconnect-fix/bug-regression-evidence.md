# Bug Regression Evidence: Algorithm Server Auto Reconnect

## Bug Summary
The main program no longer automatically reconnects or restarts the algorithm server after disconnect.

## Expected Behavior
The main program should restart or reconnect the algorithm server when the server process is missing, when the process exists but port 30415 is not listening, or when a short-link ONLINE request fails at the socket layer.

## Reproduction
Local regression reproduction:
- RED: `python -m unittest tests.test_algorithm_reconnect_policy` -> FAIL, `classify_algorithm_process_health` missing, ONLINE short-link did not enable restart on socket failure, and PAAA did not use port health.
- RED: `python -m unittest tests.test_algorithm_reconnect_policy` -> FAIL, `SharedTcpClient` did not fail fast when process start/restart failed.

## Root Cause
The main-program short-link ONLINE path disabled process restart on socket error with `restart_process_on_error=False`. `PAAA.start_process_if_needed()` also treated an existing `ocrapp_pureray.exe` process as healthy even when port 30415 was not listening. Finally, `SharedTcpClient` ignored a failed process start/restart result and continued with the socket request.

## Regression Test
Added `D:\ProjectPackage\Vein\sqw\Vein\tests\test_algorithm_reconnect_policy.py`.

GREEN: `python -m unittest tests.test_algorithm_reconnect_policy` -> PASS
GREEN: `python -m unittest discover -s tests` -> PASS
GREEN: `python -m py_compile GLPyModule\Project\PAAA\PAAA.py GLPyModule\JExtension\VeinTreat\VeinTreat.py bin\Python\slicer\util.py` -> PASS
GREEN: `python -m unittest -k reconnect test_api_server.ApiServerTests` -> PASS

## Verification
- `python -m unittest tests.test_algorithm_reconnect_policy` from `D:\ProjectPackage\Vein\sqw\Vein` -> PASS, 4 tests.
- `python -m unittest discover -s tests` from `D:\ProjectPackage\Vein\sqw\Vein` -> PASS, 10 tests.
- `python -m py_compile GLPyModule\Project\PAAA\PAAA.py GLPyModule\JExtension\VeinTreat\VeinTreat.py bin\Python\slicer\util.py` from `D:\ProjectPackage\Vein\sqw\Vein` -> PASS.
- `python -m unittest -k reconnect test_api_server.ApiServerTests` from `D:\ocr3\resource\pywrapper` -> PASS, 5 tests.

## Risk And Scope
Scope is limited to the main-program algorithm server reconnect path:
- `PAAA.start_process_if_needed()` now requires both process and port readiness.
- Stale `ocrapp_pureray.exe` processes are terminated before restart when port 30415 is not ready.
- ONLINE short-link clients invoke the existing restart hook on socket error or timeout.
- `SharedTcpClient` fails fast when the process start/restart precondition fails.

Risk: formal machine runtime timing still needs validation, especially server startup latency after process restart.

## Blockers
Formal runtime reconnect verification must be performed on the formal machine.

## Follow-Up Actions
On the formal machine, test:
- Kill `ocrapp_pureray.exe`, then trigger an ONLINE request from the main program; expect a new process to start.
- Leave `ocrapp_pureray.exe` running but make port 30415 unavailable/not listening; expect stale process restart.
- Watch logs for `process_health=stale_port`, `terminating stale algorithm process`, and `restart_process completed`.
