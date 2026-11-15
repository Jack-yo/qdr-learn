# QDR 统一浅色界面与涨跌配色（2026-11-15）

本次是 **实际 UI 样式改造，不修改行情、研究模型和预测结果**。主工作台 /studio 和旧版高级研究页面 /factors、/strategies、/backtests、/paper 等沿用同一浅色设计方向。

## 视觉约定

- 浅色背景和白色卡片：画布 #F5F7FB、卡片 #FFFFFF、细边框 #DFE6EE、正文 #213047、辅助文字 #64758B。
- 数据优先：轻量阴影、更易读的表格、明确的选中态。L1 原本确认的结构保持不变：紧凑市场栏 → H1/H3/H5 → 计算明细 → 原始指标与前向评分。
- 美股默认 **绿涨红跌**：上涨 #087E5C、下跌 #CA3D50、震荡 #587AAF；顶部可点选切换为红涨绿跌，浏览器保存偏好。切换只改变样式，任何数值不变。
- 涨跌与系统健康分开：系统成功/失败/警告、资格未通过等徽标保持固定语义颜色，不因涨跌配色切换而颠倒。
- 指标风险属性保持中性：价格回报和相对强弱的方向值可用红绿；其它原始指标水平并非“涨好跌坏”，只将上期变化差额用红绿展示。
- 红绿之外必须同时有 +/-、上涨/下跌或文字状态，不单靠颜色传达含义。

## 文件

- src/quant_research/assets/v4_ui_light.css：统一浅色覆盖层；保留原 V4、L1 V2/V3 的布局和响应式结构，最后加载新主题。其旧规则映射部分基于 2026-11-15 的 CSS，未来新增组件应同步补充浅色样式。
- src/quant_research/assets/v4_ui_theme.js：顶部红绿切换和 localStorage 偏好。
- src/quant_research/v4_shell.html：浅色主题资源及配色按钮。
- src/quant_research/assets/v4_ui_market_v3.js：SPY 收益、相对强弱、指标增量的方向数值着色。
- src/quant_research/assets/studio.css：旧版高级研究侧栏、CTA、表格同步浅色化。
- src/quant_research/web.py：前端资源访问白名单。

## 验证

在项目根目录运行：

    python -m pytest -q tests/test_v4_light_theme.py tests/test_l1_v3_ui.py tests/test_l1_v3_shell_integration.py tests/test_v4_ui_shell.py tests/test_v4_ui_browser.py

建议桌面和平板/手机宽度检查导航、表格、L1 预测计算明细、原始指标区和模型状态。Playwright 有 Chromium 时检查真实计算颜色与配色偏好在重新加载后保持不变。

**本次不改后端计算和 Alpaca 数据契约，也不会通过主题操作触发训练、冻结或修改归档。**
