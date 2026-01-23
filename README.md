# Unified CCGP Scraper Framework

统一的中国政府采购网站采集框架。

## 支持的站点

| 站点 | 验证码类型 | 状态 |
|------|-----------|------|
| **江苏** (Jiangsu) | OCR 图片验证码 | ✅ |
| **新疆** (Xinjiang) | 阿里云滑块验证码 | ✅ |
| **浙江** (Zhejiang) | 无（标准 REST API） | ✅ |

## 项目结构

```
ccgp/
├── ccgp_core/          # 核心框架
│   ├── spider.py       # BaseSpider 基类
│   ├── antibot.py      # 反爬虫处理
│   └── human_track.py  # 人类轨迹模拟
├── ccgp_sites/         # 站点实现
│   ├── _registry.py    # 站点自动发现
│   ├── jiangsu/        # 江苏站点
│   ├── xinjiang/       # 新疆站点
│   └── zhejiang/       # 浙江站点
├── scripts/            # 入口脚本
│   └── run_site.py     # 统一运行入口
└── tests/              # 测试用例
```

## 快速开始

### 运行采集

```bash
# 运行江苏采集
python scripts/run_site.py jiangsu

# 运行新疆采集（带日期过滤）
python scripts/run_site.py xinjiang --start-date 2026-01-01 --end-date 2026-01-15

# 运行浙江采集
python scripts/run_site.py zhejiang
```

### 通用参数

| 参数 | 说明 |
|------|------|
| `--start-date YYYY-MM-DD` | 开始日期 |
| `--end-date YYYY-MM-DD` | 结束日期 |
| `--keywords "kw1" "kw2"` | 关键词过滤 |
| `--region CODE` | 地区代码或名称 |
| `--max-pages N` | 最大页数（默认 100） |
| `--max-results N` | 最大结果数（默认 1000） |
| `--resume` | 断点续传 |
| `--non-interactive` | 非交互模式 |
| `--verbose` | 详细日志 |

### 示例

```bash
# 新疆站点：搜索乌鲁木齐地区的医疗相关公告
python scripts/run_site.py xinjiang --keywords "医疗" --region 650100 --start-date 2026-01-01 --end-date 2026-01-15

# 非交互模式（适用于定时任务）
python scripts/run_site.py jiangsu --non-interactive --max-pages 10
```

## 测试

```bash
# 运行全部测试
python -m pytest

# 运行特定站点测试
python -m pytest tests/test_jiangsu_spider.py -v
```

## 添加新站点

1. 创建目录 `ccgp_sites/<site_name>/`
2. 创建 `impl.py`，定义继承 `BaseSpider` 的类
3. 实现必需的抽象方法：
   - `get_landing_url()` - 返回着陆页 URL
   - `_do_probe_request()` - 执行探测请求
   - `fetch_page_items(page_no)` - 获取列表页数据
   - `extract_item_timestamp(item)` - 提取时间戳
   - `extract_item_id(item)` - 提取项目 ID
   - `fetch_detail(item_id)` - 获取详情页
   - `save_detail(item, detail, base_dir)` - 保存详情
4. 创建 `adapter.py`，导出爬虫类
5. 创建 `config.py`，设置默认配置
6. 添加测试文件 `tests/test_<site>_spider.py`

站点会被 `ccgp_sites/_registry.py` 自动发现。

## 开发工具

```bash
# 收集页面信息（用于分析新站点）
python collect_page_info.py

# 分析页面信息，生成骨架代码
python analyze_page_info_output.py
```

## 文档

- [测试工作流](docs/testing_workflow.md)
- [AI 助手规则](.agent/rules/)
