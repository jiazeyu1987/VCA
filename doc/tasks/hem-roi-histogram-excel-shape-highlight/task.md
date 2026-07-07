# HEM ROI 直方图 Excel 形状高亮增强

## 目标
- 每个 ROI 增加 0~255 灰度直方图小图。
- 当前序列可导出 Excel，包含所有图片的所有 ROI 指标与直方图。
- 每个 ROI 支持独立矩形/椭圆形状、位置和大小。
- 高亮定义支持固定灰度值和基线倍数两种模式，并可保存恢复。

## 里程碑
- [x] 建立任务记录并检查当前实现。
- [x] 补充 ROI 形状、直方图、高亮、Excel 导出测试。
- [x] 实现 ROI 定义、统计、直方图绘制与保存。
- [x] 实现当前序列 Excel 导出。
- [x] 验证、提交、推送并发布。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed

## 完成说明
- ROI1~ROI4 支持独立矩形/椭圆形状、位置、大小，并保存到 `settings.hem_roi2_batch_analyzer.roi_definitions`。
- ROI 统计支持 0~255 灰度直方图、椭圆 mask 像素统计、固定灰度值/基线倍数高亮规则。
- GUI 右侧 ROI 卡片显示直方图，主界面支持导出当前序列 Excel。
- Excel 导出包含 `Summary`、`Frame_ROI_Stats`、`Histograms`、`ROI_Config` 四个 Sheet。
