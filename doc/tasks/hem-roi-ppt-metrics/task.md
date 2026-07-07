# HEM ROI PPT 指标补齐

## 目标
- 按 PPT 要求补齐每个 ROI 的灰度分布、阈值高亮、基线差异和 HEM 面积类指标。
- 右侧 ROI 统计卡片展示当前帧指标，并在可用时展示相对基准帧的差异。
- 保持现有 ROI 绘制、时间轴和单序列分析流程。

## 里程碑
- [x] 梳理 PPT ROI 指标到实现清单。
- [x] 扩展 ROI 统计计算与侧栏显示。
- [x] 补充测试覆盖新 ROI 指标。
- [x] 运行验证并记录任务结果。
- [x] 提交推送并发布。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed - ROI 灰度分布、阈值高亮、基线差异和 HEM 面积指标已补齐，验证、提交、推送和发布均已完成。
