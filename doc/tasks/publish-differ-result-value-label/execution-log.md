# Execution Log

BDD: Publish updated differ label release -> Given the source repository has the `X/Y` differ label change and the release repository is clean, When publishing is requested, Then the release script packages OCRSERVER, commits and pushes release output, and source `main` is pushed afterward.

Inspection: source `main` is ahead of `origin/main` by 1 commit before publish.

Inspection: release repository `D:\ocr3\VA` is clean on `main`.

RED: not applicable for this publish-only task; no new production behavior or release-script change was introduced in this task.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_api_server.py` -> PASS, 64 tests.

GREEN: `$env:PYTHONDONTWRITEBYTECODE='1'; python -m unittest test_server_scripts.py` -> PASS, 10 tests.

GREEN: `cmd /c closeserver.bat` -> PASS, no listener on port `30415` and no `ocrapp_pureray` process.

GREEN: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\publish_release.ps1` -> PASS.

Publish output: stopped server precheck returned no listener on port `30415` and no `ocrapp_pureray` process.

Publish output: packaged with `D:\miniconda3\envs\houyang\python.exe`.

Publish output: created `D:\ocr3\dist\pywrapper_api_server\pywrapper_api_server.exe`.

Publish output: created `D:\ocr3\dist\OCRSERVER\ocrapp_pureray.exe`.

Publish output: deployed to `D:\ProjectPackage\Vein\sqw\Vein\OCRSERVER\ocrapp_pureray.exe`.

Publish output: created `D:\ocr3\dist\pywrapper_api_server.zip` and `D:\ocr3\dist\OCRSERVER.zip`.

Release git: `D:\ocr3\VA` commit `2bdac0e` (`release: OCRSERVER 2026-05-27 18:10:22`) pushed to `origin/main`.

Final release check: `git -C D:\ocr3\VA status --short --branch` -> clean on `main...origin/main`.

GREEN: `python C:\Users\BJB110\.codex\skills\task-closeout-cleanup\scripts\task_closeout.py --task-id publish-differ-result-value-label --mode preview` -> PASS, keep `task.md` and `execution-log.md`, delete `<none>`, blocked `<none>`.
