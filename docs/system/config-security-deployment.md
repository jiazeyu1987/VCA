# Config Security Deployment

## Purpose and Scope

Define configuration, security, deployment, and observability requirements for the algorithm session recording package feature. The design follows the repository's strict no-fallback policy: when recording is enabled, required recording prerequisites must be present and failures must be explicit.

## Evidence Reviewed

- `settings` is a JSON file at the repository root and is already read by `load_offline_config`.
- Existing server runtime writes logs through `build_logger`.
- Existing server paths use local Windows directories such as `D:/software_data`.
- `publish_release.bat` and `tools/publish_release.ps1` package the algorithm server for release.
- Project baseline says this Windows machine normally has no device connected, while published code must preserve real device connectivity.

## Configuration

Add this root-level object to `settings`:

```json
{
  "session_recording": {
    "enabled": true,
    "output_dir": "D:/software_data/session_packages",
    "frame_format": "png",
    "max_writer_queue": 256,
    "include_online_response": true,
    "include_trace_json": true,
    "package_on_finish": true
  }
}
```

Validation rules:

- `enabled` is required and must be boolean.
- If `enabled=true`, `output_dir` is required and must be non-empty.
- `frame_format` is required and must be exactly `png`.
- `max_writer_queue` is required and must be an integer greater than zero.
- `include_online_response`, `include_trace_json`, and `package_on_finish` are required booleans.

No default fallback path should be introduced for `output_dir` when recording is enabled. If a deployment wants a different storage location, it must set it explicitly.

## Secrets

No new secret is introduced.

Existing TCP password behavior remains unchanged. The package contains ultrasound images and treatment metadata, so the output directory must be treated as sensitive local medical data storage even though no credential is added.

## Permissions

The algorithm server process must have:

- Read access to `settings`.
- Write access to `session_recording.output_dir`.
- Permission to create temporary directories, files, zip files, and delete completed `.partial` directories under `output_dir`.

If permissions are missing, startup or first recording session must fail explicitly. The recorder must not switch to another directory.

## Security Controls

Required controls:

- Keep package generation local to the algorithm server machine.
- Do not upload packages automatically.
- Do not include the TCP password in manifest, events, results, or trace.
- Sanitize config stored in manifest so only recording-relevant non-secret values are written.
- Use package-relative paths inside `manifest.json`, `events.jsonl`, `trace.json`, and `checksums.json` where possible.
- Keep absolute final image/database paths only in offline result summaries if they are already part of the existing OFFLINE response contract.

Data sensitivity:

- Recorded ultrasound images are medical data.
- Packages should be copied only through approved operational processes.
- Any later analysis tool should read packages locally or from an approved data store, not from arbitrary network locations.

## Deployment

Implementation files to include in release:

- `resource/pywrapper/session_recorder.py`
- updated `resource/pywrapper/api_server.py`
- updated `resource/pywrapper/test_api_server.py`
- updated root `settings`

Release package requirements:

- `publish_release.bat` must include the new Python module in packaged output.
- Published build must keep existing real-device `PyMobileComm` connectivity behavior.
- Recording must not require the local test-only `offline_screenshot_test` path.

Local verification can use fake frames and fake provider data. Real-device verification must be performed on a device-connected machine before relying on production packages for analysis.

## Observability

Add structured log events:

- `SESSION_RECORDING config_loaded`
- `SESSION_RECORDING session_started`
- `SESSION_RECORDING frame_recorded`
- `SESSION_RECORDING online_recorded`
- `SESSION_RECORDING stop_requested`
- `SESSION_RECORDING package_finalize_begin`
- `SESSION_RECORDING package_finalized`
- `SESSION_RECORDING failed`

Each log event should include:

- `session_id`
- `point_id` when available
- `package_path` when available
- frame count or online count when relevant
- explicit error string on failure

Metrics are file/log based in the first implementation. No new metrics service is introduced.

## Open Questions

- Whether package retention should be enforced by age, count, or disk size requires an operational decision.
- Whether packages should be encrypted at rest depends on the target deployment policy and is outside the first implementation.

## Design Blockers

No deployment blocker exists for documentation. Implementation release should wait until unit tests pass and real-device E2E is run on a connected machine.
