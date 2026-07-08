# HEM ROI 当前参数显示与形状等效切换

## 目标
- ROI1~ROI4 卡片始终显示当前预览实际使用的 X/Y/宽/高。
- ROI 形状在矩形和椭圆之间切换时共用同一个外接框参数，不重新计算、不清空、不缩放。
- 保持现有 `roi_definitions[ROI].rect` 和 `shape` 数据模型不变。

## 里程碑
- [x] 建立任务记录并确认 bat 对应入口文件。
- [x] 补充 ROI 当前参数显示与形状等效切换回归测试。
- [x] 实现当前预览参数同步和形状切换补齐逻辑。
- [x] 运行验证并记录证据。
- [ ] 提交、推送、发布并再次推送。

## 预期验证
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py`
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer`

## Current Status
completed - ROI1~ROI4 卡片会同步显示当前预览实际 X/Y/宽/高；矩形/椭圆切换共用同一外接框参数，切换后参数保持不变。

## 验证结果
- `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS。
- `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS，37 tests OK。
