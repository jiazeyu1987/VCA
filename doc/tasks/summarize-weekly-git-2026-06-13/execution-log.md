# Execution Log

- Goal: Summarize this week's algorithm git and main program git commits into 6 concise Chinese items.
- Date range: 2026-06-08 00:00:00 to 2026-06-13 23:59:59.
- Repository mapping:
  - Main program git: `D:\ocr3`, remote `https://github.com/jiazeyu1987/VCA.git`.
  - Algorithm git: `D:\ocr3\VA`, remote `https://github.com/jiazeyu1987/VA.git`.
- Verification:
  - Main program git commits inspected: 7.
  - Algorithm git commits inspected: 8.
  - Main program themes: focus overlay offset, OFFLINE diagnostics, ROI4 validation error handling, ROI4 bottom-region geometry, ROI4-primary frame selection, ROI2-only final classification with offset ROI, source-aware debug final filenames.
  - Algorithm git themes: OCRSERVER release package updates, `ocrapp_pureray.exe`, `_internal/base_library.zip`, `settings`, `_internal/settings`.
  - Final output: 6 items, under 400 Chinese characters.
- Final summary:
  1. 主程序：新增焦点线 `y_offset_mm`，按深度换算下移，显示偏移不影响判定锚点。
  2. 主程序：补齐离线结束诊断，记录后处理、ROI、保存、DB 更新等阶段耗时。
  3. 主程序：修复 ROI4 越界导致 stop 等待 20 秒，改为明确检测错误返回。
  4. 主程序：ROI4 从固定矩形改为底部比例区域，默认取图像底部 30%。
  5. 主程序：离线帧选择改为 ROI4 优先、ROI1 备选；最终红绿只按 ROI2，并支持偏移 ROI。
  6. 算法 git：同步 6/9-6/11 多版 OCRSERVER 发布包、exe/base_library/settings，包含焦点偏移和 ROI4 底部区域配置。
- Status: Completed.
