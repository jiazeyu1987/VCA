# Execution Log

## BDD Scenarios
- BDD: ROI 灰度分布统计 -> Given 当前帧已有 ROI 定义, When 预览刷新, Then 每个 ROI 显示均值、灰度密度、标准差、中位数、中位数绝对偏差、偏度、峰度和百分位数。
- BDD: ROI 阈值高亮统计 -> Given 灰度阈值基于当前 ROI 均值倍率生成, When 当前帧刷新, Then 每个 ROI 显示阈值、高亮像素数、高亮面积、高亮比例和高亮像素标准差。
- BDD: ROI 基线差异 -> Given 当前 sequence 有基准帧, When 浏览非基准帧, Then 每个 ROI 显示相对基准帧均值差、百分比变化和高亮面积变化。

## TDD Evidence
- RED: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> FAIL, 新增 ROI 指标测试暴露灰度转换函数引用错误，并确认 HEM z-score 边界像素按 `>= 3` 计入。
- GREEN: `python -B -m py_compile tools\hem_roi2_batch_analyzer.py tools\test_hem_roi2_batch_analyzer.py` -> PASS
- GREEN: `python -B -m unittest tools.test_hem_roi2_batch_analyzer` -> PASS, 21 tests OK。

## Completed Work
- 按 PPT 要求补齐每个 ROI 的灰度分布类指标：平均灰度、平均灰度密度、标准差、中位数、中位数绝对偏差、百分位数。
- 补齐阈值高亮类指标：高亮阈值、高亮像素数、高亮面积、高亮比例、高亮像素标准差。
- 补齐基线对比与 HEM 类指标：较基线均值差、百分比变化、标准差差异、中位数差异、高亮面积差、HEM 面积(z>=3)。
- 右侧 ROI 统计卡片改为滚动面板，ROI1/ROI2/ROI3/ROI4 均显示同一套指标。
