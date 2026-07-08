# HEM ROI 统计两列显示

## 目标
- ROI 统计卡片内指标由 4 组横向列改为 2 组横向列。
- 保持短 key 和最多 3 位小数显示不变。
- 不改变底层统计计算、CSV 或 Excel 导出精度。

## 里程碑
- [x] 建立任务记录并确认当前为 4 组列显示。
- [x] 将 ROI 卡片内统计项改为 2 组列。
- [x] 更新回归测试并运行验证。
- [ ] 提交、推送、发布并再次推送。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed - ROI 统计卡片内指标已由 4 组列改为 2 组列；短 key 和最多 3 位小数显示保持不变。

## 验证结果
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS。
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS，38 tests OK。
