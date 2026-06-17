# Offline First Frame Before

## Goal

Use the first OFFLINE frame as the final before image. ROI1 boundary selection must no longer replace before, while after selection continues to use the existing ROI1 boundary logic.

## Milestones

- [x] Record BDD/TDD expectations.
- [x] Add failing regression coverage for first-frame before.
- [x] Update ROI1 boundary selection to keep the first before.
- [x] Run targeted and full verification.

## Expected Verification

- ROI1 boundary OFFLINE logs do not contain `before_selected`.
- `roi1_boundary_interval_selected.before_index` points to frame 1.
- Existing after selection remains `roi1_boundary_after2`.

## Current Status

Completed.
