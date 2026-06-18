# Frontend Design

## Purpose and Scope

This design intentionally does not add a new frontend. The current repository exposes the algorithm server through a local TCP API in `resource/pywrapper/api_server.py`, and the requested recording feature is server-side data capture for later analysis. The first implementation should keep the main program protocol unchanged and generate local analysis packages that can be opened by later tooling.

The user-visible behavior is operational rather than visual: after a treatment session finishes, a `session_<id>.zip` package is produced in the configured recording output directory. Operators can locate the package path in server logs and, if needed, from a future API response field after implementation approval.

## Evidence Reviewed

- `resource/pywrapper/api_server.py` currently handles `ONLINE`, `OFFLINE`, and `SHUTDOWN` request types through a socket server.
- `OfflineSessionManager` already owns OFFLINE start/stop state, frame buffering, final output saving, and diagnostic logging.
- `PyMobileCommProvider` and `MobileCommEngine` already receive ultrasound image matrices and store recent `FrameSnapshot` objects.
- `settings` currently stores OFFLINE peak detection, temporary frame debug output, final image output, result flag, and database root settings.
- No web routes, desktop windows, or browser-based UI entry points are present for this feature.

## Pages and Routes

No frontend page or route is introduced in this design.

Existing protocol remains:

- `ONLINE;31415;{...}` returns the current converted online provider response.
- `OFFLINE;31415;{"point_id":..., "time_out":..., "is_save":...}` starts or stops an OFFLINE session depending on active point state.
- `SHUTDOWN;31415;{...}` requests server shutdown.

The recording feature must not require a new UI path in the first implementation. A later analysis viewer may consume the package, but that viewer is outside this server-side design.

## Components

No visual components are added.

Operational surfaces:

- Server log entries for package creation, package path, and recording failures.
- Local package files under the configured recording output directory.
- Optional future response field `session_package_path` on successful OFFLINE stop responses can be considered only if the main program can safely ignore extra JSON fields. The first implementation should prefer logs and package files to avoid changing the UI contract.

## State and Data Flow

The main user flow is:

1. Main program sends first OFFLINE request for `point_id`.
2. Algorithm server starts the OFFLINE capture session and starts a recording session.
3. The recorder writes frame images and event lines while the session is active.
4. Main program continues sending ONLINE requests; each ONLINE request is recorded as timing and result metadata when an OFFLINE recording session is active.
5. Main program sends the second OFFLINE request for the same `point_id`.
6. Algorithm server finalizes OFFLINE results and asks the recorder to close the package.
7. The recorder emits the zip package path to logs.

## Error States

Errors are surfaced through server logs and existing API error responses. Recording must fail fast when enabled:

- Missing recording configuration prevents server startup or OFFLINE start, depending on where the missing value is detected.
- Recorder directory creation failure returns an explicit recording error.
- Event log write failure returns or raises an explicit recording error.
- Frame write failure returns or raises an explicit recording error.
- Package finalization failure returns an explicit `recording_finalize_failed` style error.

The implementation must not silently skip frame saving, silently disable recording, or produce a success response while the package is incomplete.

## Accessibility and Responsive Behavior

No UI is introduced, so accessibility and responsive layout do not apply. Future HTML analysis reports should be designed separately with keyboard navigation, readable tables, and scalable charts.

## Open Questions

- Whether the main program should display the package path in its own UI is outside this server-side design.
- Whether a future analysis viewer should be a standalone local HTML report or an integrated desktop page is outside this first implementation.

## Design Blockers

No frontend blocker exists for the first implementation because the required behavior is server-side recording and package generation.
