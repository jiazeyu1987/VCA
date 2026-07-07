# HEM ROI 宽屏布局优化

## 目标
- 图片预览区左对齐显示，减少左侧空白浪费。
- 右侧 ROI 统计信息区域加宽，提升文本可读性。
- ROI1/ROI2/ROI3/ROI4 统计卡片改为 2×2 紧凑布局，默认最大化窗口下不依赖纵向滚动条。

## 里程碑
- [x] 固化宽屏布局回归测试。
- [x] 改造图片锚点与 ROI 统计面板布局。
- [x] 运行验证并记录结果。
- [x] 提交推送并发布。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed - 图片预览已左上锚定，右侧 ROI 统计面板已加宽，并改为 2×2 卡片布局；验证、提交、推送和发布均已完成。
