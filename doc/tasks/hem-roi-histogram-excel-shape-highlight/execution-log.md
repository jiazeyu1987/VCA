# Execution Log

## BDD Scenarios
- BDD: ROI 形状统计 -> Given ROI1~ROI4 可独立设置矩形或椭圆, When 刷新当前帧, Then 统计与直方图只使用对应形状内的像素。
- BDD: ROI 直方图显示 -> Given 当前帧已有 ROI 统计, When 时间轴或 ROI 参数变化, Then 每个 ROI 卡片显示对应 0~255 灰度直方图小图。
- BDD: 高亮定义可配置 -> Given 用户选择固定灰度值或基线倍数, When ROI 统计刷新, Then 高亮阈值和高亮指标使用所选规则。
- BDD: 当前序列 Excel 导出 -> Given 当前加载一个 sequence, When 点击导出当前序列 Excel, Then 输出一个包含 Summary、Frame_ROI_Stats、Histograms、ROI_Config 的 xlsx。

## TDD Evidence
- RED: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> FAIL, expected missing APIs for `roi_gray_histogram`, ROI `shape`, `highlight_rule`, `roi_definitions`, `save_visual_analysis_settings`, and `export_sequence_excel`.
- GREEN: `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS.
- GREEN: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS, 30 tests.
