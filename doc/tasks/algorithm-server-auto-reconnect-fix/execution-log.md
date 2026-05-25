# Execution Log: Algorithm Server Auto Reconnect Fix

BDD: Restart stale algorithm process -> Given `ocrapp_pureray.exe` is present but port 30415 is not listening, When the main program prepares an algorithm request, Then it must treat the process as stale and restart it instead of reporting the process as healthy.

BDD: Online socket failure restarts algorithm process -> Given a short-link ONLINE request encounters a socket error or timeout, When the request fails at the transport layer, Then the request client must invoke the controlled algorithm process start/restart path.

## Evidence
- Investigation baseline: service-side reconnect tests already passed; regression is in main-program reconnect policy.
- RED: `python -m unittest tests.test_algorithm_reconnect_policy` -> FAIL, expected missing reconnect policy: `classify_algorithm_process_health` absent, ONLINE short-link used `restart_process_on_error=False`, and PAAA did not use port health when deciding restart.
- RED: `python -m unittest tests.test_algorithm_reconnect_policy` -> FAIL, expected missing fail-fast handling: `SharedTcpClient` did not stop when `PAAA.start_process_if_needed()` returned failure.
- GREEN: `python -m unittest tests.test_algorithm_reconnect_policy` -> PASS
- GREEN: `python -m py_compile GLPyModule\Project\PAAA\PAAA.py GLPyModule\JExtension\VeinTreat\VeinTreat.py bin\Python\slicer\util.py` -> PASS
- GREEN: `python -m unittest discover -s tests` -> PASS
- GREEN: `python -m unittest -k reconnect test_api_server.ApiServerTests` -> PASS

## Root Cause
The main program had two disabled reconnect paths after the short-link change: ONLINE request clients were created with `restart_process_on_error=False`, and process health in `PAAA.start_process_if_needed()` returned healthy based only on process name. A stale `ocrapp_pureray.exe` process with no 30415 listener was therefore treated as usable.

## Fix Summary
- Added explicit algorithm process health classification: `ready`, `stale_port`, `missing_process`, and `port_ready_without_process`.
- Restart now handles `stale_port` by stopping the stale `ocrapp_pureray.exe` process before starting a new process.
- `port_ready_without_process` fails clearly instead of accepting an unknown listener as the algorithm server.
- ONLINE short-link requests now enable `restart_process_on_error=True`.
- `SharedTcpClient` now fails the request when algorithm process start/restart fails.

## Runtime Blocker
Formal runtime reconnect verification is deferred because this machine cannot run the actual main-program/device environment.
