# CI/CD Environment Evidence

## Environment

- Workspace: `D:\ocr3`
- Release repository: `D:\ocr3\VA`
- Published runtime package source: `D:\ocr3\dist\OCRSERVER`
- Analyzer release artifact: `session_timeline_analyzer.exe`
- Required release Python: standalone 64-bit CPython 3.9.13 at `D:\Python39\python.exe`
- Real-device extension requirement: `resource\pywrapper\PyMobileComm.pyd` imports `python39.dll` and must load during release preflight.

## Commands

- Build analyzer exe: `.\package_session_timeline_analyzer.bat`
- Publish full release: `.\publish_release.bat`
- Validate release script tests: `D:\Python39\python.exe -B -m unittest resource.pywrapper.test_server_scripts`
- Validate server packaging preflight: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\package_pywrapper_server.ps1 -PreflightOnly`
- Validate analyzer packaging preflight: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\package_session_timeline_analyzer.ps1 -PreflightOnly`
- Validate this evidence: `D:\Python39\python.exe C:\Users\BJB110\.codex\skills\ci-cd-environment-delivery\scripts\validate_cicd_environment.py --evidence docs\environments\ci-cd-evidence.md`

## Secrets

- No new secrets are required.
- Existing git remote access for the main repository and `VA` release repository is required.

## Pipeline

- `publish_release.bat` calls `tools\publish_release.ps1`.
- `tools\publish_release.ps1` verifies both package preflights before stopping the server, builds OCRSERVER, builds `session_timeline_analyzer.exe`, copies it into `dist\OCRSERVER`, syncs `dist\OCRSERVER` into `VA`, stages all release changes, commits only when Git detects changes, and pushes `VA` to `origin/main`.
- Packaging requires the exact configured standalone 64-bit Python 3.9 runtime. It fails before server shutdown if the runtime version, PyInstaller dependencies, or `PyMobileComm` real-device extension cannot load; it does not fall back to Conda or another Python.

## Verification

- Official CPython 3.9.13 installer signature -> Valid, signer Python Software Foundation; installed only at `D:\Python39` without changing the global PATH.
- `D:\Python39\python.exe -B -m unittest resource.pywrapper.test_server_scripts` -> PASS, 13 tests.
- Server packaging preflight -> PASS, including standalone 64-bit Python 3.9, PyInstaller, Pillow, NumPy, and `PyMobileComm` import checks.
- Analyzer packaging preflight -> PASS, including standalone 64-bit Python 3.9, PyInstaller, Pillow, and Tkinter import checks.
- `D:\Python39\python.exe -B -m unittest test_session_recorder test_api_server` from `resource\pywrapper` -> PASS, 129 tests.
- PowerShell scriptblock parse for `tools\publish_release.ps1` -> PASS.
- `git diff --check -- tools/publish_release.ps1 resource/pywrapper/test_server_scripts.py docs/environments/ci-cd-evidence.md` -> PASS.
- CI/CD evidence validation -> PASS.
- `.\publish_release.bat` built OCRSERVER, built `session_timeline_analyzer.exe`, copied it to `D:\ocr3\dist\OCRSERVER\session_timeline_analyzer.exe`, and created VA release commit `9506d63`.
- The initial VA push hit a TLS EOF transport error; `git -C VA -c http.version=HTTP/1.1 push -u origin HEAD:main` pushed `9506d63` successfully.
- `git -C VA ls-files session_timeline_analyzer.exe` -> PASS, the analyzer exe is tracked by the VA release repository.
- `D:\ocr3\VA\session_timeline_analyzer.exe --self-test-load <sample package>` -> PASS, exit code 0.

## Rollback

- Revert the main repository release automation commit.
- Re-run `publish_release.bat` from the reverted code to publish a VA release without the analyzer exe, or revert the latest `VA` release commit directly if only the release repository needs rollback.

## Blockers

- No current Python-runtime blocker. The former Conda dependency was removed after explicit user approval to use standalone Python and explicit rejection of Conda.
