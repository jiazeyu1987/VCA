# Execution Log

## BDD Scenarios
- BDD: ROI 统计紧凑显示 -> Given 右侧显示 4 个 ROI 统计卡片, When 程序最大化显示, Then ROI 文本使用更小字体并减少行距，尽量完整展示。
- BDD: ROI 区域保存即时生效 -> Given 用户在 ROI 卡片中填写区域信息, When 点击保存 ROI 区域, Then 当前图像上的 ROI 框和右侧统计立即按新区域刷新。
- BDD: ROI 区域持久化 -> Given 用户保存 ROI 区域配置, When 下次启动程序, Then 默认加载上次保存的 ROI 区域。

## TDD Evidence
- RED: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> FAIL, 新增 ROI 编辑保存测试发现缺少紧凑字体常量、ROI 覆盖配置字段和保存 ROI 区域持久化函数。
- GREEN: `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS
- GREEN: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS, 24 tests OK。

## Completed Work
- 右侧 ROI 统计文字改为更小字号，并压缩统计行距，减少显示不全的问题。
- 每个 ROI 卡片顶部新增 X/Y/宽/高输入框，可直接填写 ROI 区域。
- 新增“保存ROI区域”按钮，保存后当前预览和统计立即刷新。
- ROI 区域保存到 `settings` 的 `hem_roi2_batch_analyzer.roi_rect_overrides`，下次打开自动恢复上次保存值。
- ROI 覆盖区域只作用于当前 GUI 工具的预览和统计，不改写服务器算法字段，避免影响其它流程。
- 提交并推送代码变更，随后运行 `publish_release.bat` 完成 OCRSERVER 发布并再次推送。
