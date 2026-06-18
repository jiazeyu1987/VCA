# CI/CD Environment Evidence

## Environment

- Workspace: `D:\ocr3`
- Release repository: `D:\ocr3\VA`
- Published runtime package source: `D:\ocr3\dist\OCRSERVER`
- Analyzer release artifact: `session_timeline_analyzer.exe`

## Commands

- Build analyzer exe: `.\package_session_timeline_analyzer.bat`
- Publish full release: `.\publish_release.bat`
- Validate release script tests: `D:\miniconda3\envs\houyang\python.exe -B -m unittest resource.pywrapper.test_server_scripts`
- Validate this evidence: `D:\miniconda3\envs\houyang\python.exe C:\Users\BJB110\.codex\skills\ci-cd-environment-delivery\scripts\validate_cicd_environment.py --evidence docs\environments\ci-cd-evidence.md`

## Secrets

- No new secrets are required.
- Existing git remote access for the main repository and `VA` release repository is required.

## Pipeline

- `publish_release.bat` calls `tools\publish_release.ps1`.
- `tools\publish_release.ps1` stops the server, builds OCRSERVER, builds `session_timeline_analyzer.exe`, copies it into `dist\OCRSERVER`, syncs `dist\OCRSERVER` into `VA`, stages all release changes, commits only when Git detects changes, and pushes `VA` to `origin/main`.

## Verification

- `D:\miniconda3\envs\houyang\python.exe -B -m unittest resource.pywrapper.test_server_scripts` -> PASS, 11 tests.
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

- None currently.
