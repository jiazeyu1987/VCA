# Offline Finalization Background Optimization

## Goal

Remove previous-session debug image and session-package finalization from the next treatment's critical path while preserving treatment detection, result persistence, complete debug frames, complete session packages, and explicit failure reporting.

## Milestones

- [x] Record the observable behavior, performance budget, and current blocking reproduction.
- [x] Add a failing regression test proving that a new treatment can capture its first frame while the previous treatment is still finalizing.
- [x] Refactor OFFLINE session ownership and recording finalization so previous-session persistence does not block the next start.
- [x] Verify result integrity, session-package integrity, failure behavior, and relevant regressions.
- [ ] Complete independent review, cleanup, commit, push, release publish, and final push.

## Expected Verification

- A deterministic concurrency test proves the next `wait_before_capture=true` request returns before the previous session's delayed debug/package finalization completes.
- Existing OFFLINE start/stop, debug output, session recording, ONLINE recording, and failure-path tests pass.
- No treatment frame detection, result calculation, or real-device connection capability is removed or downgraded.
- Performance evidence separates start acknowledgement latency from background persistence latency.
- `resource\pywrapper\api_server.py`, `resource\pywrapper\session_recorder.py`, and changed tests compile.

## Current Status

blocked

## Blockers

- Release publish is blocked: required runtime `D:\miniconda3\envs\houyang\python.exe` is missing. The repository explicitly forbids substituting another Python runtime, and `publish_release.bat` would stop the service before the package script reports this failure.
- Real-device timing remains blocked until the new hardware is connected.

## Completed Work

- Confirmed the stop waiter holds the OFFLINE manager lock through full persistence.
- Confirmed recorder ownership is implicit and singleton, so overlapping finalization would reject or misroute a new session.
- Defined the handoff boundary after shared final outputs and before session-unique debug/package persistence.
- Added deterministic failing tests for next-treatment acknowledgement and recorder session isolation.
- Added a real OFFLINE start/stop regression test for `SessionRecorderConfig(enabled=False)` and captured the expected RED failure at the session-ID assertion.
- Treated an explicitly disabled recorder as inactive across OFFLINE start, frame recording, stop, handoff, and finalization while preserving the enabled-recorder session-ID assertions.
- Added the recording-enabled state to OFFLINE start diagnostics.
- Completed review-fix-loop round 2 with `final_decision: pass` and no required changes.
- Consolidated explicit session ownership, safe handoff ordering, shutdown draining, and concurrency verification rules into the existing backend/data-model design documents.

## Verification Evidence

- RED command and expected failures are recorded in `execution-log.md`.
- The focused disabled-recorder regression test passes.
- The complete changed recorder and API suites pass: 129 tests.
- Compilation passes for `api_server.py`, `session_recorder.py`, `test_api_server.py`, and `test_session_recorder.py`.
- Independent review round 2 passed.
- Final no-bytecode regression runs passed: 129 API/recorder tests and 28 server/probe tests.
- Task closeout cleanup preview and apply passed with no blocked or ambiguous paths.
- Implementation commit `b98dfbd` was pushed to `origin/codex/offline-finalization-background-optimization`.
- Release preflight stopped before `publish_release.bat` because the required `houyang` runtime is missing; no service process or release repository was modified.

## Cleanup Candidates

- `.review-fix-loop/runs/offline-finalization-background-20260807/`
