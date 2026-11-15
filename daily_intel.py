# -*- coding: utf-8 -*-
"""内容情报站: EasySpider + Scrapling + Crawl4AI 三件套串联管道

  Stage 1 [Scrapling]  GitHub Trending 快照入库 + 变化检测 (复用 monitor_watch)
  Stage 2 [Crawl4AI]   新上榜(或TOP3)仓库页面 → Markdown 语料存档
  Stage 3 [分析]       GEO 审计(复用 geo_analysis.audit) + 关键词 → 选题情报报告
  Stage 4 [EasySpider] 可选: CLI 无头跑任务 / 消化 Data 里已有采集结果

用法:
  python daily_intel.py                # 1→3 全管道
  python daily_intel.py --with-es 4    # 外加: EasySpider CLI 跑任务 4 (地震台网) 并消化结果
  python daily_intel.py --es-process   # 只消化 EasySpider 已有采集结果 (Data/*.xlsx)
报告: crawler-lab/reports/ , 语料: crawler-lab/corpus/
"""
import os, sys, glob, json, re, subprocess, datetime, argparse, collections, asyncio

sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("CRAWL4AI_NO_CLOUD_NOTICE", "1")
HERE = os.path.dirname(os.path.abspath(__file__))
ES_ROOT = r"G:\RPA\EasySpider-app\EasySpider_windows_x64"
PROXY = os.environ.get("HTTPS_PROXY")

import monitor_watch as mw          # Stage 1
from geo_analysis import audit      # Stage 3

STOP = set("the a an and or of to in on for with is are was were be been this that it its as at by from we you they he she not but can will your our their about more than then if so do does did has have had new get how what why when who all any use using used one two v s t i skip content navigation menu sign products platform build ship enterprise explore marketplace pricing signin login http https com org www github googlechrome openai alibaba readme md license about star fork issues pull request commits branch main master actions projects security insights releases contributors".split())

def keywords(markdown: str, top=6):
    # 剥离链接 URL 和导航噪音后再统计
    clean = re.sub(r"\]\(https?://[^)]*\)", "]", markdown)
    clean = re.sub(r"https?://\S+", " ", clean)
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", clean)
    cnt = collections.Counter(w.lower() for w in words if w.lower() not in STOP)
    return [w for w, _ in cnt.most_common(top)]

def extract_body(markdown: str, min_len=60) -> str:
    """提取 markdown 中最长的连续正文块 (README 正文), 摆脱导航/侧栏噪音"""
    runs, cur = [], []
    for raw in markdown.splitlines():
        ls = raw.strip()
        if len(ls) >= min_len and ls.count("](http") <= 2 and ls.count("](/") <= 2:
            cur.append(ls)
        else:
            if cur:
                runs.append(cur); cur = []
    if cur:
        runs.append(cur)
    if not runs:
        return " ".join(markdown.split())[:2000]
    best = max(runs, key=lambda r: sum(len(x) for x in r))
    return " ".join(best)

def new_repos(st, url):
    ts_list = st.ts_list(url)  # v2 存储层: MySQL/SQLite 同一套 API
    if len(ts_list) < 2:
        return []
    ts_new, ts_old = ts_list[0], ts_list[1]
    old = {h for _, _, h in st.rows_at(url, ts_old)}
    cur = st.rows_at(url, ts_new)
    return [(r, t, h) for r, t, h in cur if h and h not in old]

async def crawl_repos(targets, corpus_dir):
    """targets: [(label, url)]; 返回 [(label, url, audit_dict, excerpt)]"""
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
    out = []
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False, proxy=PROXY)) as crawler:
        for label, url in targets:
            cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
            r = await crawler.arun(url=url, config=cfg)
            if not r.success:
                out.append((label, url, {"error": r.error_message[:100]}, "", []))
                continue
            md = r.markdown or ""
            slug = re.sub(r"[^A-Za-z0-9_-]+", "_", url.split("github.com/")[1] if "github.com" in url else url)
            with open(os.path.join(corpus_dir, slug + ".md"), "w", encoding="utf-8") as f:
                f.write(md)
            a = audit(r.html, md, url)
            body = extract_body(md)
            out.append((label, url, a, body[:220], keywords(body)))
    return out

def build_report(repos, es_note, out_dir):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# 📊 内容情报站日报 ({ts})", "",
             f"> 管道: Scrapling 监控 → Crawl4AI 语料 → GEO 分析 → EasySpider 采集", ""]
    lines.append("## 仓库情报")
    all_kw = collections.Counter()
    for label, url, a, excerpt, kw in repos:
        if "error" in a:
            lines.append(f"- ❌ **{label}** — 抓取失败: {a['error']}")
            continue
        all_kw.update(kw[:3])
        lines.append(f"### {label}  (`GEO {a['geo_score']}分`)")
        lines.append(f"- 链接: {url}")
        lines.append(f"- 结构: h2×{a['h2']} h3×{a['h3']} 列表×{a['lists']} 外链×{a['ext_links']} | 词数 {a['words']}")
        lines.append(f"- 高频词: {', '.join(kw) or '-'}")
        lines.append(f"- 摘录: {excerpt[:150]}...")
        lines.append("")
    if all_kw:
        top = [w for w, _ in all_kw.most_common(8)]
        lines += ["## 💡 选题建议 (规则版)", ""]
        if len(top) >= 2:
            lines += [f"{i+1}. 「{top[i]}」×「{top[(i+1) % len(top)]}」— 两个热词结合的场景实测文"
                      for i in range(min(3, len(top) - 1))]
        lines.append("")
    lines.append(f"## 🕷️ EasySpider RPA 环节")
    lines.append(f"- {es_note}")
    path = os.path.join(out_dir, f"intel_{datetime.datetime.now():%Y%m%d_%H%M}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path, all_kw

def newest_xlsx():
    files = glob.glob(os.path.join(ES_ROOT, "Data", "**", "*.xlsx"), recursive=True)
    return max(files, key=os.path.getmtime) if files else None

def run_es_task(task_id):
    bat = os.path.join(ES_ROOT, "EasySpider", "resources", "app", "chrome_win64", "execute_win64.bat")
    cfg = os.path.join(ES_ROOT, "tasks", f"{task_id}.json")
    print(f"[EasySpider] CLI 跑任务 {task_id}: {cfg}")
    before = set(glob.glob(os.path.join(ES_ROOT, "Data", "**", "*.xlsx"), recursive=True))
    try:
        subprocess.run(["cmd", "/c", bat, "--config", cfg, "--user_data", "1"],
                       cwd=ES_ROOT, timeout=240, capture_output=True)
    except subprocess.TimeoutExpired:
        pass
    after = set(glob.glob(os.path.join(ES_ROOT, "Data", "**", "*.xlsx"), recursive=True))
    new = after - before
    if new:
        print(f"[EasySpider] 产出: {os.path.basename(list(new)[0])}")
        return list(new)[0]
    return None

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-es", help="EasySpider 任务 ID, 如 4")
    ap.add_argument("--es-process", action="store_true", help="消化 Data 里已有 xlsx")
    ap.add_argument("--feishu", action="store_true", help="报告推送到飞书群 (需 feishu_config.json)")
    args = ap.parse_args()

    corpus = os.path.join(HERE, "corpus"); rep = os.path.join(HERE, "reports")
    os.makedirs(corpus, exist_ok=True); os.makedirs(rep, exist_ok=True)

    # ---- Stage 1: Scrapling 监控 ----
    print("=" * 60, "\n[Stage 1] Scrapling 监控 GitHub Trending")
    st = mw.open_storage("auto")     # v2 存储层: MySQL 优先, 失败自动降级 SQLite
    pool = mw.ProxyPool()
    mw.one_round(mw.DEFAULTS["url"], mw.DEFAULTS["sel"], st, pool)
    news = new_repos(st, mw.DEFAULTS["url"])
    ts_list = st.ts_list(mw.DEFAULTS["url"])
    all_rows = st.rows_at(mw.DEFAULTS["url"], ts_list[0]) if ts_list else []
    if news:
        targets = [(f"新上榜 #{r} {t}", "https://github.com/" + h.strip("/")) for r, t, h in news]
    else:
        targets = [(f"TOP{r} {t}", "https://github.com/" + h.strip("/")) for r, t, h in all_rows[:3]]
        print("  (无新上榜, 深度分析当前榜单 TOP3)")
    print(f"  → 深度分析目标 {len(targets)} 个")

    # ---- Stage 2: Crawl4AI 语料 ----
    print("\n[Stage 2] Crawl4AI 抓取语料")
    repos = asyncio.run(crawl_repos(targets, corpus))
    for label, url, a, _ex, _kw in repos:
        print(f"  {'✓' if 'error' not in a else '✗'} {label} | GEO {a.get('geo_score','-')} | 词数 {a.get('words','-')}")

    # ---- Stage 3: 报告 ----
    print("\n[Stage 3] GEO 分析 + 生成情报报告")

    # ---- Stage 4: EasySpider ----
    es_note = "未执行 (用 --with-es <任务ID> 跑一次, 或 --es-process 消化已有结果)"
    if args.with_es:
        x = run_es_task(args.with_es) or newest_xlsx()
        if x and x not in set():
            es_note = f"任务 {args.with_es} 产出: {os.path.basename(x)}"
        else:
            es_note = f"任务 {args.with_es} 未产出 xlsx (可能需输入参数或交互式任务)"
    elif args.es_process:
        x = newest_xlsx()
        if x:
            es_note = f"消化已有结果: {os.path.basename(x)}"
        else:
            es_note = "Data 目录暂无采集结果 (先在 EasySpider 里执行任务)"
    else:
        x = newest_xlsx()
        if x:
            es_note = f"发现已有结果: {os.path.basename(x)} (--es-process 可消化)"

    path, all_kw = build_report(repos, es_note, rep)
    print(f"\n{'='*60}\n✅ 报告: {path}")
    print(f"   语料: {len(repos)} 篇 @ corpus/ | EasySpider: {es_note}")

    if args.feishu:
        import feishu_send
        resp = feishu_send.send_report(path)
        ok = str(resp.get("StatusCode")) == "0" or resp.get("code") == 0 or resp.get("code") == "0"
        print(f"{'📨 已推送飞书' if ok else '⚠️ 飞书推送失败: ' + json.dumps(resp, ensure_ascii=False)[:150]}")
