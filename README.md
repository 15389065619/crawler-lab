# 内容情报站 (crawler-lab)

一套 **Python 单运行时** 的内容情报管道: 监控 → 语料 → 分析 → 推送, 零 Docker / 零数据库服务依赖。

三件套分工: **EasySpider** 零代码 RPA 采集 · **Scrapling** 反检测监控 · **Crawl4AI** LLM 语料。

## 管道架构

```
[Scrapling]  GitHub Trending 快照入库 (SQLite) + 新上榜检测
     ↓
[Crawl4AI]   新仓库页面 → 干净 Markdown 语料 (corpus/)
     ↓
[GEO 审计]   九维评分 (标题层级/结构化内容/统计数字/FAQ体/
             schema.org/可引用段落/外链/体量/meta) + 关键词提取
     ↓
[日报]       reports/intel_*.md → 飞书群机器人推送
     ↓
[EasySpider] 可选: GUI 采集结果 (Data/*.xlsx) 并入报告
```

## 文件一览

| 文件 | 用途 |
|---|---|
| `daily_intel.py` | ⭐ 主管道: 一条命令跑完全流程并推飞书 |
| `monitor_watch.py` | 定时监控, 变化检测 (新上榜/跌出/排名变动) |
| `geo_analysis.py` | GEO 竞品审计 (DOM 解析版, 9 维评分) |
| `feishu_send.py` | 飞书群机器人推送 (支持签名校验/关键词) |
| `easyspider_pipeline.py` | EasySpider 任务扫描 + 采集结果消化 (可选 LLM) |
| `scrapling_lab.py` | Scrapling 四大能力实验台 (反爬/自适应/语义定位/性能) |
| `cf_breakthrough.py` | Cloudflare 突破实战 (solve_cloudflare) |
| `demo_crawl4ai.py` / `demo_scrapling.py` | 两个库的最小对比 demo |

## 快速开始

```bash
pip install "scrapling[fetchers]" crawl4ai playwright pandas openpyxl beautifulsoup4 lxml requests
python -m playwright install chromium

# 每日情报 (监控 → 语料 → 分析 → 飞书)
python daily_intel.py --feishu

# 消化 EasySpider 采集结果
python easyspider_pipeline.py --list          # 扫任务
python easyspider_pipeline.py --process x.xlsx

# 定时监控 / GEO 审计
python monitor_watch.py --interval 30
python geo_analysis.py https://你的目标站
```

## 配置

复制 `feishu_config.example.json` → `feishu_config.json`, 填入你的飞书群机器人 webhook
(获取: 飞书群 → 设置 → 群机器人 → 自定义机器人)。`keyword` 字段对应机器人开启的关键词校验。

代理: 境外目标站自动走 `HTTPS_PROXY` 环境变量 (见各脚本 `PROXY_HOSTS` 白名单)。

LLM 增强 (可选): `set LLM_API_KEY=xxx` 后 EasySpider 管道自动启用 AI 分析,
兼容 OpenAI/智谱/DeepSeek (`LLM_BASE_URL` / `LLM_MODEL` 可覆盖)。

## 实测数据

- Scrapling 隐身浏览器 vs 普通 HTTP: sannysoft 反爬检测 **31/31 vs 0/8**
- Scrapling 解析 518KB 页面: **25ms** (BeautifulSoup 210ms, 8.4x)
- Cloudflare 突破 (scrapingcourse.com 教学靶场): solve_cloudflare **25s 自动过盾**
- 全管道单轮耗时: **约 40s**

## License

MIT
