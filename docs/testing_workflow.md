# 测试工作流（系统集成）

## 目标与范围
本工作流覆盖三类测试：单元/回归测试、站点级集成测试、系统集成回归。重点关注框架稳定性、站点抓取链路、验证码与反爬流程的可回归性。

## 环境准备
- 进入可执行环境：`conda activate web`
- 确保依赖就绪（OCR 相关测试需要 `paddleocr`；Xinjiang 站点可能依赖浏览器/自动化工具）。
- 如需配置凭证或代理，仅在本地 `.env` 中维护，勿提交仓库。

## 测试分层与执行顺序
### 1) 单元/回归测试（本地快速回归）
在仓库根目录执行：
```bash
conda activate web
python -m pytest
```
建议生成可追踪报告（便于后续集成或归档）：
```bash
python -m pytest --junitxml tests/report/junit.xml
```

### 2) 站点级集成测试（最小范围跑通）
使用统一入口 `scripts/run_site.py`，控制规模以减轻站点压力：
```bash
python scripts/run_site.py jiangsu --max-pages 1 --max-results 3
python scripts/run_site.py zhejiang --max-pages 1 --max-results 3
python scripts/run_site.py xinjiang --max-pages 1 --max-results 3
```
验收要点：
- 结果目录在 `results/<site>/search_results_<site>_YYYYMMDD_HHMMSS/`。
- 必须生成 `search_results.json`，且 `details/` 下有按条目保存的明细文件。

### 3) 系统集成回归（跨站点验证与断点续跑）
建议每次发布前执行一次：
1. 全量回归测试：`python -m pytest`
2. 站点联跑：对 3 个站点使用相同过滤参数（例如日期区间）。
3. 断点续跑验证：先跑一段中断后，带 `--resume` 再跑一次，确认不重复写入且能继续进度。

示例：
```bash
python scripts/run_site.py jiangsu --start-date 2026-01-01 --end-date 2026-01-07 --max-pages 2
python scripts/run_site.py jiangsu --resume
```

## 报告与复盘（可选增强）
仓库自带测试循环辅助脚本：`scripts/test_cycle_helper.py`。推荐流程：
```bash
python scripts/test_cycle_helper.py init
python -m pytest --junitxml tests/report/junit.xml
python scripts/test_cycle_helper.py parse
python scripts/test_cycle_helper.py summary
```
输出将保存到 `tests/report/`（JUnit 报告与最终总结），方便长期追踪与系统集成回归复盘。

## 失败处理与回归要求
- 如果涉及江苏验证码或新疆滑块/浏览器链路，必须补齐或更新测试用例。
- 测试失败需记录：失败用例、复现命令、环境信息（Python/conda 版本）。
- 修复后优先跑 `python -m pytest`，再进行站点级集成测试确认。
