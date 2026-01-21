# 自动化修改规则（AGENT）

本文件用于约束自动化改动，确保江苏/新疆采集功能稳定。

## 项目定位

- 本仓库为脚本式 Python 项目（无包发布诉求）
- 目标是：在可扩展的框架结构下稳定采集多个站点

## 高风险区域（可调整）

以下逻辑属于高风险区，任何微小变更都可能导致采集失败，但允许基于回归测试进行调整与优化：

- 江苏：`ccgp_sites/jiangsu/impl.py` 中验证码识别链路相关方法
  - `preprocess_captcha`
  - `preprocess_captcha_for_local_ocr`
  - `recognize_captcha_local`
  - `recognize_captcha_api`
  - `recognize_captcha`
  - `get_captcha`
- 新疆：`ccgp_sites/xinjiang/impl.py` 中滑块、浏览器与人工干预相关方法
  - `_capture_captcha_images`
  - `_detect_gap_distance`
  - `_generate_human_track`
  - `_handle_slider_captcha`
  - `_hide_browser_window_immediately`
  - `_ensure_window_offscreen`

高风险区域的变更必须满足：
- 明确的变更动机与回归策略

- 补齐/更新离线回归测试，覆盖关键分支与边界条件

## 允许的重构范围

- `ccgp_core/`：通用工具与运行框架
- `ccgp_sites/*/adapter.py` 与 `ccgp_sites/*/config.py`：站点接口适配与配置整理
- `scripts/`：入口脚本薄化、统一参数解析（不得改变站点行为）


## 安全与配置

- 不要在仓库中写入任何真实 token、cookie、账号信息
- `.env` 不应提交；只保留 `.env.example` 作为示例



如果涉及站点新增/站点入口调整，额外确认：

- `ccgp_sites/_registry.py` 能发现新站点
