# HEM ROI 可编辑紧凑布局

## 目标
- 缩小右侧 ROI 统计字体，让 2×2 ROI 卡片尽量完整显示。
- 每个 ROI 卡片支持填写 ROI 区域信息。
- 保存 ROI 区域后立即刷新当前图像和统计，ROI 区域随之改变。
- 保存后的 ROI 区域写入配置文件，下次打开沿用上次保存值。

## 里程碑
- [x] 检查当前 ROI 设置和界面布局代码。
- [x] 增加 ROI 区域编辑与保存逻辑。
- [x] 缩小字体并优化统计面板显示。
- [x] 补充测试并运行验证。
- [x] 提交推送并发布。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed - ROI 区域输入、保存后即时刷新、下次启动恢复上次保存值，以及更小字号紧凑显示均已完成；验证、提交、推送和发布均已完成。
