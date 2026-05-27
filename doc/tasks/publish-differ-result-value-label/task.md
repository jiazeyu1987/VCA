# Publish Differ Result Value Label

## Goal

Publish the current OCRSERVER build that changes the first differ judgement line from `OK/FAIL` to `<actual>/green`, commit the release output, and push the source repository `main`.

## Milestones

1. Completed: Inspect source and release repository state.
2. Completed: Verify relevant tests for the differ label change and publish scripts.
3. Completed: Run `tools\publish_release.ps1`.
4. Completed: Run closeout cleanup preview and record final status.
5. Pending: Commit this task record in the source repository.
6. Pending: Push source repository `main` to `origin/main`.

## Expected Verification

- Relevant differ overlay and script tests pass before publish.
- `tools\publish_release.ps1` completes successfully or fails fast with a concrete blocker.
- Release repository `D:\ocr3\VA` gets a new pushed commit when package output changes.
- Source repository `main` is pushed to `origin/main`.
- Task closeout cleanup preview has no blockers.

## Current Status

Completed. Source repository commit and push are the final shell actions for this task.

## Results So Far

- Source `main` is ahead of `origin/main` by 1 commit (`2ef3e48`).
- Release repository `D:\ocr3\VA` is clean on `main...origin/main`.
- Environment/deployment target: local OCRSERVER package from `D:\ocr3` to release repository `D:\ocr3\VA`, pushed to `origin/main`.
- Build/package command: `powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\publish_release.ps1`.
- Required secrets: existing git remotes only; no new secrets added.
- Release output: `D:\ocr3\VA` commit `2bdac0e` pushed to `origin/main`.
- Rollback: revert or reset the `D:\ocr3\VA` release repo to the previous release commit `07f92c1`, then push the selected release commit to `origin/main`.
- Closeout cleanup preview: ready, no delete candidates, no blockers.
