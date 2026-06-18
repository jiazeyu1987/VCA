# Backend API Design

## Purpose and Scope

Add a server-side recording module to the algorithm server so each accepted OFFLINE treatment session can produce a complete data package for later analysis. The package must include ultrasound frame images from session start through session completion, OFFLINE timestamps, ONLINE request timestamps, algorithm duration, result summaries, and a trace file that timeline tools can read.

The design keeps recording logic separate from algorithm logic. `resource/pywrapper/api_server.py` should call a new recorder module at explicit lifecycle points; the recorder owns file layout, event schemas, trace generation, and zip packaging.

## Evidence Reviewed

- `FrameSnapshot` contains `image`, `seq`, and `ts`, which gives a natural frame identity and source timestamp.
- `MobileCommEngine._on_image_info_received` copies image matrices, increments `_frame_seq`, and stores frame history with `time.time()`.
- `PyMobileCommProvider.fetch_online` already enforces reconnect behavior, fetches provider data, and logs online timepoints.
- `handle_request` converts ONLINE provider data into the existing response JSON.
- `ApiServer._send_response` has the socket dispatch boundary and can measure end-to-end server duration for each request.
- `OfflineSessionManager.handle` decides whether an OFFLINE request starts or stops a session.
- `OfflineSessionManager._run_session` captures OFFLINE frames and performs finalization.
- Existing code already uses fail-fast validation for required OFFLINE settings such as `peak_detect` and `offline_tmp_frames`.

## Modules

New module:

- `resource/pywrapper/session_recorder.py`
  - `SessionRecorderConfig`
  - `SessionDataRecorder`
  - `RecordingSession`
  - package schema helpers
  - Chrome Trace JSON writer
  - zip finalizer

Existing module integration:

- `resource/pywrapper/api_server.py`
  - Extend `OfflineConfig` or add a parallel config object for `session_recording`.
  - Parse `settings.session_recording`.
  - Pass recorder into `OfflineSessionManager` and `ApiServer`.
  - Call recorder on OFFLINE start, frame capture, stop request, final result, and online request completion.

Recommended lifecycle calls:

```python
recorder.start_session(point_id=point_id, meta=...)
recorder.mark_offline_start(...)
recorder.record_frame(frame, frame_seq=..., frame_ts=..., source="offline_capture", tag=...)
recorder.mark_offline_stop_requested(...)
recorder.record_online_request(trace_id=..., started_ns=..., ended_ns=..., response_summary=...)
recorder.record_offline_result(session.response, result_paths=...)
recorder.finish_session(...)
```

The algorithm server should only pass events and images. It should not know package file names, trace formatting details, or zip internals.

## API Contracts

External TCP request/response contract remains compatible:

- No new request type is required for the first implementation.
- OFFLINE start and stop semantics remain the same.
- ONLINE response body remains the same.
- Recording adds local side effects and log records.

Settings contract:

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

Required when `enabled=true`:

- `output_dir`
- `frame_format` equal to `png`
- `max_writer_queue` greater than zero

The first implementation should not add compatibility aliases. Missing or invalid values must raise a clear `ValueError`.

Recorder session contract:

- One active recorder session maps to one accepted OFFLINE point session.
- `session_id` format: `YYYYMMDD_HHMMSS_mmm_point_<point_id>_<short_random>`.
- The recorder writes to a temporary directory first: `<output_dir>/<session_id>.partial/`.
- Final package path: `<output_dir>/<session_id>.zip`.
- On successful finalization, the `.partial` directory may be removed only after the zip file is fully written and verified.

## Error Model

Recording failures must be explicit:

- Config parse error: raise `ValueError` before server enters normal serving.
- Cannot create output directory: raise `OSError` at first session start.
- Queue full: raise `RuntimeError("session recording writer queue is full")`.
- Background writer exception: store the exception, stop accepting new records, and raise it on the next recorder call and during `finish_session`.
- Package finalization error: return or raise an explicit finalization failure so the OFFLINE response is not reported as a complete recording success.

No silent downgrade is allowed:

- Do not disable recording automatically.
- Do not drop frames when the writer cannot keep up.
- Do not switch to JPEG or lower resolution.
- Do not write placeholder image files.
- Do not produce an empty or partial zip as success.

## Transactions and Idempotency

File write transaction model:

1. Create `<session_id>.partial/`.
2. Append events to `events.jsonl` and write frames/results inside the partial directory.
3. Write `manifest.json` last with counts and timestamps.
4. Write `trace.json` from recorded events.
5. Create `<session_id>.zip.tmp`.
6. Move `session_id.zip.tmp` to `session_id.zip` with `os.replace`.
7. Remove `.partial` only after the zip exists and can be opened by `zipfile.ZipFile`.

Idempotency:

- A recorder session can be finished once.
- Repeated `finish_session` calls after success should return the same package path.
- Repeated `finish_session` after failure should raise the stored failure until a new session starts.
- Extra OFFLINE requests already return `offline_ignored_extra_request`; recorder should not create additional packages for ignored requests.

## Open Questions

- Whether `session_package_path` should be added to OFFLINE stop JSON responses should be decided after confirming the main program tolerates extra fields.
- Whether package retention limits are needed depends on disk capacity and expected case volume; no automatic deletion is included in the first implementation.

## Design Blockers

Real-device E2E cannot be completed on this machine because project baseline says the current machine normally has no device connected. Unit and fake-provider integration tests can still verify package correctness.
