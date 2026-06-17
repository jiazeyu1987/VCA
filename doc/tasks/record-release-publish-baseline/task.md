# Task: Record Release Publish Baseline

## Goal
Record a durable workspace rule that each completed task must push code, run `publish_release.bat`, and push again after the release publish step.

## Milestones
- [completed] M1: Capture the approved baseline wording.
- [completed] M2: Verify the baseline is not already recorded and append it to `AGENTS.md`.
- [completed] M3: Verify the recorded rule and complete task closeout.

## Expected Verification
- Confirm `D:\ocr3\AGENTS.md` is the workspace-root target file.
- RED: Verify the requested release/push baseline is absent before editing.
- GREEN: Re-read `AGENTS.md` and verify the canonical baseline line is present after editing.
- Run task closeout cleanup preview before final completion.

## Current Status
Completed.

## Completed Work
- User approved the baseline wording: `完成任务后先推送代码，再执行publish_release.bat发布并再次推送一次。`
- Verified the baseline was absent before editing.
- Appended the approved canonical baseline line to `D:\ocr3\AGENTS.md`.
- Verified the baseline is present after editing.
- Ran task closeout cleanup preview; no delete candidates, blockers, or warnings were reported.

## Remaining Blockers
- None.
