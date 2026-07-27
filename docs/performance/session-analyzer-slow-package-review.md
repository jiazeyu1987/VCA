# Session Analyzer Slow Package Review

## Scope and Critical Paths

- Scope: loading `session_20260618_144419_985_point_114271_60a7493a.zip` in the standalone session timeline analyzer.
- Critical path: open zip, read `manifest.json`, parse `events.jsonl`, populate timeline/table, and display the first available PNG preview.

## Targets or Explicit Target Blockers

- No formal latency target exists yet for session package loading.
- This review will report observed local timings and identify the dominant bottleneck.

## Capacity Assumptions and Data Volume

- Package path: `C:\Users\BJB110\Desktop\session_20260618_144419_985_point_114271_60a7493a.zip`
- Zip size: 7,685,868 bytes.
- Zip members: 57.
- PNG frame members: 52.
- Event count: 57.
- Event type counts: 1 `offline_start`, 52 `offline_frame`, 1 `offline_stop_requested`, 1 `offline_result`, 1 `offline_end`, 1 `package_finalized`.
- Manifest frame count: 52.
- Manifest online event count: 0.

## Cost Drivers and Owners

- Runtime cost driver: local CPU, disk IO, zip decompression, and image decode.
- Owner: local analysis workflow.

## Quotas, Limits, and Scaling Constraints

- Current onefile exe size in `VA`: about 31.6 MB.
- PyInstaller onefile executables extract their bundled Python, Tkinter, Tcl/Tk, Pillow, and DLL runtime before user code runs. That extraction and Windows security scanning are the dominant startup cost for this package.

## Verification Method and Results

- Zip central directory open/list: about 0.002 seconds.
- `manifest.json` read: about 0.0001 seconds.
- `events.jsonl` read: about 0.0003 seconds.
- JSON event parse: about 0.0005 seconds.
- Direct `load_session_package` runs: about 0.0009 to 0.0010 seconds.
- First image preview after direct load: about 0.0032 to 0.0036 seconds after warm-up.
- GUI `load_path` and timeline render after app is already created: about 0.010 to 0.046 seconds.
- Source Python CLI self-test: about 0.16 to 0.29 seconds.
- `VA\session_timeline_analyzer.exe --self-test-load <package>`: first measured run about 3.365 seconds, subsequent runs about 2.0 seconds.

## Findings

- PASS: The package itself is small for the current analyzer design.
- PASS: Zip read, JSON parse, and PNG preview are fast.
- FAIL: Single-file exe startup adds about 2 to 3 seconds before useful work completes.
- NOT APPLICABLE: Online event rendering is not a factor for this package because `online_event_count` is 0.

## Release Impact and Downstream Work

- No immediate code defect was found in package parsing.
- For repeated analysis, keep the analyzer open and use `Open Zip` or `Open Folder`; switching packages inside the running app avoids repeated onefile startup extraction.
- If faster double-click startup is required, publish an additional onedir analyzer release beside the single exe. It would still run without Python installed, but would be a folder containing the exe and `_internal` runtime files instead of one standalone exe.
