# Task: Summarize Weekly Git Commits 2026-06-13

## Goal
整理本周算法 git 和主程序 git 的提交内容，输出 6 条、不超过 400 字的中文总结。

## Milestones
- [x] Identify repositories for algorithm git and main program git.
- [x] Inspect this week's commit history in both repositories.
- [x] Condense commit themes into 6 concise items.
- [x] Record verification evidence and final status.

## Expected Verification
- Confirm repository paths and remotes.
- Confirm commit date range: 2026-06-08 through 2026-06-13.
- Ensure final summary has 6 items and stays under 400 Chinese characters.

## Current Status
Completed.

## Final Summary
1. 主程序：新增焦点线 `y_offset_mm`，按深度换算下移，显示偏移不影响判定锚点。
2. 主程序：补齐离线结束诊断，记录后处理、ROI、保存、DB 更新等阶段耗时。
3. 主程序：修复 ROI4 越界导致 stop 等待 20 秒，改为明确检测错误返回。
4. 主程序：ROI4 从固定矩形改为底部比例区域，默认取图像底部 30%。
5. 主程序：离线帧选择改为 ROI4 优先、ROI1 备选；最终红绿只按 ROI2，并支持偏移 ROI。
6. 算法 git：同步 6/9-6/11 多版 OCRSERVER 发布包、exe/base_library/settings，包含焦点偏移和 ROI4 底部区域配置。
