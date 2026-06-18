# Data Model

## Purpose and Scope

Define the local file data model for algorithm session recording packages. The package must support later timeline analysis, frame quality analysis, algorithm result analysis, and audit of whether the package is complete.

The package is file-based, not database-based. This avoids adding a new persistent service and matches the current algorithm server style, which already writes final images, result flags, and debug artifacts to local disk.

## Evidence Reviewed

- Existing OFFLINE debug output writes PNG frames and JSONL metadata in `OfflineSessionManager._flush_buffered_frames`.
- Existing final outputs are PNG images written by `write_png`.
- Existing diagnostics use JSON-safe event payloads through `safe_json_text`.
- Existing `settings` has local Windows paths under `D:/software_data`.
- Existing tests already assert JSONL and image output behavior for OFFLINE debug saves.

## Entities

### Session Package

Zip file:

```text
session_<session_id>.zip
  manifest.json
  events.jsonl
  frames/
  results/
  trace.json
  checksums.json
```

`checksums.json` is included as required integrity metadata even though the user-facing short format lists the main analysis files. It lets later analysis verify that frames and results match the package manifest.

### Manifest

Required fields:

- `schema_version`: string, first version `1.0`.
- `session_id`: unique string.
- `point_id`: original OFFLINE point id.
- `created_at_iso`: wall-clock ISO timestamp.
- `offline_start_epoch_ms`: first accepted OFFLINE request timestamp.
- `offline_stop_requested_epoch_ms`: matching stop request timestamp, nullable until stop is accepted.
- `offline_end_epoch_ms`: recorder finalization timestamp.
- `frame_count`: number of frame image records.
- `online_event_count`: number of ONLINE request records captured while session was active.
- `result_count`: number of JSON result files.
- `server`: host, port, executable path when available.
- `recording_config`: sanitized recording config values.
- `package_status`: `completed` or `failed`.

### Events JSONL

One JSON object per line. Required common fields:

- `schema_version`
- `session_id`
- `event_type`
- `wall_time_iso`
- `epoch_ms`
- `perf_counter_ns`

Required event types:

- `offline_start`
- `offline_frame`
- `offline_stop_requested`
- `offline_end`
- `online_request`
- `offline_result`
- `package_finalized`

Frame event fields:

- `frame_id`
- `frame_seq`
- `frame_index`
- `frame_ts_epoch_ms`
- `source`: `offline_capture` or `online_latest_frame`
- `tag`
- `path`
- `shape`
- `roi1_mean` when available
- `roi2_mean` when available
- `roi3_mean` when available

Online event fields:

- `trace_id`
- `request_started_perf_counter_ns`
- `request_ended_perf_counter_ns`
- `server_duration_ms`
- `response_kind`
- `latest_frame_seq`
- `result_path`

### Frames

All frame images are PNG files in `frames/`.

Recommended name:

```text
frames/frame_000001_seq_000000123_offline_capture.png
```

Rules:

- Preserve original pixel dimensions and channels.
- Do not resize, crop, compress to JPEG, or overlay markers for raw recorded frames.
- Derived final images can be referenced in `results/offline_result.json` but raw frame recording must remain unchanged.

### Results

Result summaries are JSON files in `results/`.

Files:

- `results/offline_result.json`
- `results/online_000001.json`
- `results/online_000002.json`

Online result summary should include the existing ONLINE response fields after conversion:

- `SkinDepth`
- `A`
- `B`
- `Alpha`
- `Depth`
- `IsFreeze`
- `isHIFU`
- `FocusPoint`

Offline result summary should include:

- `point_id`
- `success`
- `info`
- `roi2_color`
- `roi2_diff`
- `roi2_before_mean`
- `roi2_after_mean`
- `roi3_g1`
- `roi3_g2`
- `roi3_column_diff`
- `roi3_override_applied`
- `roi4` diagnostics already returned by the server
- final image paths when available

### Trace

`trace.json` uses Chrome Trace Event Format so it can be opened by Perfetto or compatible trace viewers.

Required trace events:

- `offline_session`: duration event from `offline_start` to `offline_end`.
- `offline_capture`: duration event from `offline_start` to `offline_stop_requested`.
- `online_request`: duration event per ONLINE request.
- `offline_frame`: instant event per recorded frame.
- `package_finalize`: duration event for zip finalization.

Timestamps in trace are microseconds. Durations are computed from monotonic perf-counter deltas where possible.

### Checksums

`checksums.json` maps package-relative paths to SHA-256:

```json
{
  "frames/frame_000001_seq_000000123_offline_capture.png": "sha256...",
  "events.jsonl": "sha256..."
}
```

## Relationships

- One session package has one manifest.
- One session package has many event rows.
- One `offline_frame` event references one PNG frame.
- One `online_request` event references one online result JSON file.
- One `offline_result` event references one offline result JSON file.
- `trace.json` is derived from event and duration records.
- `checksums.json` covers all package files except itself.

## State Models

Recorder session states:

- `inactive`: no active OFFLINE recording.
- `active`: OFFLINE start accepted and frames/events are being recorded.
- `stopping`: matching OFFLINE stop request accepted.
- `finalizing`: OFFLINE result and package files are being written.
- `completed`: zip package was created and verified.
- `failed`: recording encountered an explicit error.

Allowed transitions:

```text
inactive -> active -> stopping -> finalizing -> completed
inactive -> active -> failed
active -> stopping -> failed
stopping -> finalizing -> failed
finalizing -> failed
completed -> inactive
failed -> inactive after error is surfaced
```

## Migration Notes

No database migration is required.

Settings migration:

- Add `session_recording` to the root `settings` file.
- Do not reuse `offline_tmp_frames` as the package recorder config because debug frame saving and standard analysis package recording have different retention, naming, and integrity requirements.
- Existing `offline_tmp_frames` behavior remains unchanged.

## Data Integrity Rules

- `manifest.frame_count` must equal the number of frame files and the number of `offline_frame` events that reference frame files.
- Every event line must be valid JSON.
- Every result path referenced by `events.jsonl` must exist inside `results/`.
- Every frame path referenced by `events.jsonl` must exist inside `frames/`.
- `offline_end_epoch_ms` must be greater than or equal to `offline_start_epoch_ms`.
- `online_request.server_duration_ms` must be greater than or equal to zero.
- Package finalization must fail if checksum generation fails.
- A package with missing required files must not be marked `completed`.

## Open Questions

- Whether to include raw provider callback payloads in addition to converted ONLINE response summaries depends on privacy and storage needs. The first implementation records converted response summaries only.
- Whether package retention and automatic cleanup should be added depends on expected disk usage and operational policy.

## Design Blockers

No data model blocker exists for local file-package implementation. Disk capacity planning remains an operational requirement before high-volume use.
