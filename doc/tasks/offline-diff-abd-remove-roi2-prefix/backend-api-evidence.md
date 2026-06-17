# Backend API Evidence

## Scope

- Handler/service: OFFLINE diff overlay rendering in `resource/pywrapper/api_server.py`.
- API contract: OFFLINE response shape and file paths remain unchanged.
- Data contract: diff image text line 2 removes redundant `ROI2:` prefix.

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

BDD: Diff A/B/D line omits redundant ROI2 prefix -> Given the diff overlay only displays ROI2 metrics, When ROI2 A/B/D values are rendered, Then the second line is `2. A:<after>,B:<before>,D:<diff>`.

## RED Command

RED: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> FAIL, line 2 still includes `ROI2:`.

## GREEN Command

GREEN: `python -m unittest test_api_server.ApiServerTests.test_diff_overlay_first_line_shows_actual_and_success_value` -> PASS.

GREEN: `python -m unittest test_api_server` -> PASS, 100 tests.

## Contract Or Integration Verification

OFFLINE response shape and output file paths are unchanged. Diff image text line 2 is now `2. A:<after>,B:<before>,D:<diff>`.

## Observability Touchpoints

- No log schema changes.
- Diff image text is covered by unit tests.

## Blockers And Downstream Skill Needs

- None.
