# Publish ROI Marker Release

## Goal

Publish the current OCRSERVER build that includes differ-image ROI/focus markers, commit the release output, and push both the release repository and source repository.

## Milestones

1. Completed: Inspect source and release repository status.
2. Completed: Fix publish blockers in the stop script and packaging Python runtime.
3. Completed: Run `tools\publish_release.ps1` to stop, package, copy, commit, and push `D:\ocr3\VA`.
4. Completed: Prepare this task record and publish-script fixes for the source repository commit.
5. Completed: Run closeout cleanup preview and record final status.
6. In progress: Commit and push source repository `main` to `origin/main`.

## Expected Verification

- `D:\ocr3\VA` is clean before publishing.
- `tools\publish_release.ps1` completes successfully or fails fast with a concrete blocker.
- Release repository has a new pushed commit when package output changes.
- Source repository `main` is pushed to `origin/main`.
- Task closeout cleanup preview has no blockers.

## Current Status

Completed. Source repository commit and push are the final shell actions for this task.

## Results So Far

- Environment/deployment target: local OCRSERVER package from `D:\ocr3` to release repository `D:\ocr3\VA`, pushed to `origin/main`.
- Build/package command: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\publish_release.ps1`.
- Test command: `python -m unittest test_server_scripts.py`.
- Pipeline files changed: `closeserver.bat`, `tools/package_pywrapper_server.ps1`, `resource/pywrapper/test_server_scripts.py`.
- Required secrets: existing git remotes only; no new secrets added.
- Release output: `D:\ocr3\VA` commit `07f92c1` pushed to `origin/main`.
- Rollback: revert or reset the `D:\ocr3\VA` release repo to the previous release commit `f01ca3d`, then push the selected release commit to `origin/main`.
- Closeout cleanup preview: ready, no delete candidates, no blockers.
