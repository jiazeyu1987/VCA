# HEM ROI 统计四列紧凑显示

## 目标
- ROI 统计卡片内指标改为 4 组横向列显示，减少高度占用。
- 所有统计 key 显示文字不超过 4 个汉字/字符。
- GUI 统计显示的小数最多保留 3 位，不改变底层计算、CSV 或 Excel 导出精度。

## 里程碑
- [x] 建立任务记录并确认当前统计面板实现。
- [x] 补充四列布局、短标签和显示精度回归测试。
- [x] 实现紧凑统计布局和显示格式化。
- [x] 运行验证并记录结果。
- [ ] 提交、推送、发布并再次推送。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed - ROI 统计卡片内指标已改为 4 组横向列显示，key 均不超过 4 个字符，GUI 侧栏小数最多显示 3 位。

## 验证结果
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS。
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS，38 tests OK。
