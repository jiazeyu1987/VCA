# Execution Log

## BDD Scenarios
- BDD: 宽屏图片预览 -> Given 程序默认最大化运行, When 当前序列图片加载完成, Then 图片应贴近左侧预览区显示，而不是在宽预览区中居中留下大块左侧空白。
- BDD: ROI 统计宽面板 -> Given 右侧显示 ROI1/ROI2/ROI3/ROI4 统计, When 窗口最大化, Then 每个 ROI 文本应有更宽显示空间，且 4 个 ROI 以 2×2 布局展示。
- BDD: 默认无需滚动查看 ROI -> Given 当前 ROI 指标数量不变, When 右侧统计面板显示, Then 默认最大化窗口下不应依赖纵向滚动条浏览 ROI 卡片。

## TDD Evidence
- RED: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> FAIL, 宽屏布局测试发现缺少 ROI 卡片 2×2 定位辅助函数与布局常量。
- GREEN: `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS
- GREEN: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS, 22 tests OK。

## Completed Work
- 将图片预览控件锚点改为左上角，减少最大化时左侧空白。
- 将右侧 ROI 统计区域最小宽度提升到 760，并调整主布局列权重。
- 移除 ROI 统计区纵向滚动容器，ROI1/ROI2/ROI3/ROI4 改为 2×2 宽卡片布局。
- 新增布局回归测试，约束左上锚点、宽面板和 2×2 ROI 卡片定位。
- 提交并推送代码变更，随后运行 `publish_release.bat` 完成 OCRSERVER 发布并再次推送。
