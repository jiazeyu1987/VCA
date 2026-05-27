# Execution Log

BDD: Publish current OCRSERVER release -> Given the source repository contains the ROI/focus marker change and the release repository is clean, When publishing is requested, Then the release script packages OCRSERVER, commits and pushes release output, and source `main` is pushed afterward.

Inspection: source `main` was ahead of `origin/main` by 2 commits before publishing.

Inspection: release repository `D:\ocr3\VA` was clean on `main`.

RED: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\publish_release.ps1` -> TIMEOUT after 604 seconds, expected reason: `closeserver.bat` did not return and packaging did not start.

RED: `cmd /c closeserver.bat` -> TIMEOUT after 64 seconds, expected reason: current `Get-NetTCPConnection` based stop script hung even when no `30415` listener and no `ocrapp_pureray` process existed.

RED: `python -m unittest test_server_scripts.ServerScriptTests.test_close_server_bat_exists_and_targets_server_port_and_process_name test_server_scripts.ServerScriptTests.test_package_script_defaults_to_existing_py39_runtime` -> FAIL, expected reason: `closeserver.bat` did not use `netstat -ano -p tcp`, and `tools\package_pywrapper_server.ps1` defaulted to missing `D:\miniconda3\envs\py39\python.exe` instead of existing Python 3.9 runtime `D:\miniconda3\envs\houyang\python.exe`.

GREEN: `python -m unittest test_server_scripts.ServerScriptTests.test_close_server_bat_exists_and_targets_server_port_and_process_name test_server_scripts.ServerScriptTests.test_package_script_defaults_to_existing_py39_runtime` -> PASS.

GREEN: `cmd /c closeserver.bat` -> PASS, no listener on port `30415` and no `ocrapp_pureray` process.

GREEN: `D:\miniconda3\envs\houyang\python.exe -c "import sys; print(sys.executable); import PyInstaller; print('PYINSTALLER_OK')"` -> PASS.

GREEN: `python -m unittest test_server_scripts.py` -> PASS, 10 tests.

GREEN: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\publish_release.ps1` -> PASS.

Publish output: stopped server precheck returned no listener on port `30415` and no `ocrapp_pureray` process.

Publish output: packaged with `D:\miniconda3\envs\houyang\python.exe`.

Publish output: created `D:\ocr3\dist\pywrapper_api_server\pywrapper_api_server.exe`.

Publish output: created `D:\ocr3\dist\OCRSERVER\ocrapp_pureray.exe`.

Publish output: deployed to `D:\ProjectPackage\Vein\sqw\Vein\OCRSERVER\ocrapp_pureray.exe`.

Publish output: created `D:\ocr3\dist\pywrapper_api_server.zip` and `D:\ocr3\dist\OCRSERVER.zip`.

Release git: `D:\ocr3\VA` commit `07f92c1` (`release: OCRSERVER 2026-05-27 14:46:36`) pushed to `origin/main`.

Final release check: `git -C D:\ocr3\VA status --short --branch` -> clean on `main...origin/main`.

GREEN: `git diff --check -- closeserver.bat tools/package_pywrapper_server.ps1 resource/pywrapper/test_server_scripts.py` -> PASS.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_server_scripts.py` -> PASS, 10 tests.

GREEN: `python C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id publish-roi-marker-release --mode preview` -> PASS, keep `task.md` and `execution-log.md`, delete `<none>`, blocked `<none>`.
