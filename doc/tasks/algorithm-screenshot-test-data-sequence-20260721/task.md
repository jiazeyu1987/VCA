# algorithm-screenshot-test-data-sequence-20260721

## Goal
Add algorithm-server support for the VeinTreat screenshot button to save captured frames under `D:\software_data\test_data\<yyyyMMddHHmmss>\001.png`, `002.png`, `003.png` while preserving existing treatment OFFLINE save behavior.

## Milestones
- [x] Inspect OFFLINE session capture and finalization behavior.
- [x] Add RED regression coverage for test-data sequential frame saving.
- [x] Implement the dedicated request flag and server-side frame writer.
- [x] Run focused verification and record evidence.

## Expected Verification
- `resource\pywrapper\test_api_server.py` proves the frame sequence directory and names.
- Existing OFFLINE focused tests remain passing.
- `resource\pywrapper\api_server.py` compiles.

## Current Status
blocked_on_release_publish

## Remaining Blocker
- `publish_release.bat` hardcodes `D:\ocr3`, but the worktree contains unrelated pre-existing dirty changes in `resource/pywrapper/api_server.py`, `resource/pywrapper/test_api_server.py`, tools, pycache, and other files. Running the release script from this state would package non-task code, so release publish is blocked until those unrelated changes are committed, shelved, or moved out of `D:\ocr3`.
