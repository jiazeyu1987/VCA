# Execution Log: Algorithm Server Reconnect Investigation

BDD: Main program reconnects after algorithm server disconnect -> Given the main program previously had an active algorithm server connection, When the algorithm server disconnects unexpectedly, Then the main program should detect the broken connection and establish a new connection without requiring a manual restart.

## Evidence
- Current `D:\ocr3` server reconnect tests passed:
  GREEN: `python -m unittest -k reconnect test_api_server.ApiServerTests` -> PASS
- Current server-side ONLINE reconnect is still present in `resource\pywrapper\api_server.py`: `fetch_online()` calls `ensure_connected_for_online()`, which calls `RestartAdbServer()` and `Auto_Initialize()` when the device state is disconnected.
- Main-program reconnect behavior is currently disabled by `D:\ProjectPackage\Vein\sqw\Vein\GLPyModule\JExtension\VeinTreat\VeinTreat.py`: `_algorithm_online_simple_mode = True` causes reconnect scheduling, warmup, prewarm, and keepalive to return early.
- Current request dispatch creates request-scoped `util.SharedTcpClient(..., restart_process_on_error=False)`, so socket errors/timeouts do not call process restart from `SharedTcpClient._fail_request()`.
- `D:\ProjectPackage\Vein\sqw\Vein\GLPyModule\Project\PAAA\PAAA.py` checks both `process_running` and `port_ready`, but returns success as soon as the process name exists. It does not restart when the process is present but port 30415 is not listening.
- Historical regression point: commit `8033212e` ("改成短链接") introduced `_algorithm_online_simple_mode = True`, disabled the reconnect path, and added `restart_process_on_error=False` for the new request-scoped online client.
- Historical expected behavior: commit `ee159380` ("修复算法服务崩溃后主程序无法自动重连") restarted the algorithm process from the socket error path.

## Root Cause
The current main program no longer has an active automatic reconnect loop for the algorithm server. Online requests were changed to short-lived, request-scoped clients, while the previous reconnect/prewarm/keepalive path was explicitly disabled under `simple-online-mode`. At the same time, request-scoped online clients opt out of process restart on socket error/timeout, and the remaining process-start helper does not handle the "process exists but port is dead" case.

## Recommended Fix Scope
- Re-enable an explicit reconnect policy for algorithm server disconnects instead of relying on disabled keepalive code.
- Let online request socket failures trigger a controlled restart or restart scheduling path.
- Fix `PAAA.start_process_if_needed()` so process health requires both `process_running=True` and `port_ready=True`; if the process exists but port 30415 is not ready, terminate/restart that specific `ocrapp_pureray.exe` instance or report a fail-fast error.
- Add regression tests around `SharedTcpClient` error/timeout restart behavior and `PAAA.start_process_if_needed()` process-present/port-dead behavior before changing production code.
