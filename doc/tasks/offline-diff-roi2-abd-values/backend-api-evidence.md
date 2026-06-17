# Backend API Evidence

## Scope

- Handler/service: OFFLINE diff overlay rendering in `resource/pywrapper/api_server.py`.
- API contract: OFFLINE response shape and file paths remain unchanged.
- Data contract: diff image text changes to expose ROI2 A/B/D metric values.

## Auth, Permissions, Validation, And Error Behavior

- No auth or permission changes.
- No validation behavior changes.
- No persistence schema changes.

## Required Config, Services, Fixtures, And Migrations

- Config: existing OFFLINE image output settings.
- Services: none for unit tests.
- Fixtures: in-memory `OfflineSession` in `test_api_server.py`.
- Migrations: none.

## BDD Scenarios

BDD: Diff overlay shows ROI2 after before and diff values -> Given OFFLINE has computed ROI2 before mean, after mean, and diff, When diff overlay judgement lines are built, Then the overlay includes `A:<after>,B:<before>,D:<diff>`.

## RED Command

RED: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> FAIL, second ROI2 line still shows diff/threshold instead of A/B/D values.

## GREEN Command

GREEN: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS.

GREEN: `python -m unittest test_api_server` -> PASS, 100 tests.

## Contract Or Integration Verification

OFFLINE response shape and output file paths are unchanged. Diff image text now includes ROI2 A/B/D metric values.

## Observability Touchpoints

- No log schema changes.
- Diff image text is covered by unit tests.

## Blockers And Downstream Skill Needs

- None.
