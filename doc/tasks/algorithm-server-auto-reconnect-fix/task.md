# Task: Algorithm Server Auto Reconnect Fix

## Goal
Restore main-program automatic reconnect/restart behavior when the algorithm server disconnects or the `ocrapp_pureray.exe` process is present but port 30415 is not listening.

## Milestones
- [completed] M1: Add failing regression coverage for the reconnect policy.
- [completed] M2: Implement the minimal main-program reconnect fix.
- [completed] M3: Run targeted verification, record evidence, and close out.

## Expected Verification
- Regression test proves process health requires both the algorithm process and a ready TCP port.
- Regression test proves online short-link requests enable process restart on socket error or timeout.
- `py_compile` passes for changed main-program Python files.
- Runtime device verification is deferred to the formal machine because this machine has no runnable device/server environment.

## Current Status
Completed.

## Completed Work
- Added `D:\ProjectPackage\Vein\sqw\Vein\tests\test_algorithm_reconnect_policy.py`.
- Updated `D:\ProjectPackage\Vein\sqw\Vein\GLPyModule\Project\PAAA\PAAA.py` so algorithm process health requires both process presence and port readiness.
- Added stale-process handling for `ocrapp_pureray.exe`: if the process exists but port 30415 is not ready, the main program terminates that stale process and starts a fresh one.
- Updated `D:\ProjectPackage\Vein\sqw\Vein\GLPyModule\JExtension\VeinTreat\VeinTreat.py` so request-scoped ONLINE clients use `restart_process_on_error=True`.
- Updated `D:\ProjectPackage\Vein\sqw\Vein\bin\Python\slicer\util.py` so `SharedTcpClient` fails the request when `PAAA.start_process_if_needed()` fails, instead of silently continuing.

## Blockers
- Formal runtime reconnect verification cannot run on this machine.

## Final Verification
- `python -m unittest tests.test_algorithm_reconnect_policy` from `D:\ProjectPackage\Vein\sqw\Vein` -> PASS, 4 tests.
- `python -m unittest discover -s tests` from `D:\ProjectPackage\Vein\sqw\Vein` -> PASS, 10 tests.
- `python -m py_compile GLPyModule\Project\PAAA\PAAA.py GLPyModule\JExtension\VeinTreat\VeinTreat.py bin\Python\slicer\util.py` from `D:\ProjectPackage\Vein\sqw\Vein` -> PASS.
- `python -m unittest -k reconnect test_api_server.ApiServerTests` from `D:\ocr3\resource\pywrapper` -> PASS, 5 tests.

## Cleanup Keep
- doc/tasks/algorithm-server-auto-reconnect-fix/bug-regression-evidence.md
