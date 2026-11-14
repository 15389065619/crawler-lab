# -*- coding: utf-8 -*-
"""GEO 内容审计工具: 用 Crawl4AI 抓取竞品页面, 按生成式引擎优化 (GEO) 维度做规则版评分。

审计维度源自 GEO 研究结论 (KDD'24 论文 + 主流 GEO 实践):
引用源 / 统计数字 / 结构化内容 / FAQ 问答体 / 标题层级 / 可引用段落 / schema.org / meta 完整度 / 词数体量

用法: python geo_analysis.py [url1 url2 ...]   (缺省审计三个内容站)
输出: 控制台对比表 + crawler-lab/geo_report.json
"""
import asyncio, json, os, re, sys, datetime
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8")
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# github 等境外站走 Clash 代理, 国内站直连
PROXY_HOSTS = ("github.com", "google.com", "medium.com")
DEFAULT_TARGETS = [
    "https://sspai.com/post/92885",   # 少数派长文
    "https://www.cnblogs.com/cate/python/",  # 博客园栏目页
    "https://juejin.cn/post/7366358432017018931",  # 掘金技术文章
]

def need_proxy(url: str) -> bool:
    return any(h in url for h in PROXY_HOSTS)

# ---------- 规则版 GEO 审计 (DOM 解析版) ----------
def audit(html: str, markdown: str, url: str = "") -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    text = " ".join(markdown.split())
    words = len(text)
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))

    # 真实标题标签
    h1 = len(soup.find_all("h1"))
    h2 = len(soup.find_all("h2"))
    h3 = len(soup.find_all("h3"))
    # SPA 伪标题: div/p 用 title/heading 类名承载的标题 (掘金/少数派等 Vue/React 站)
    pseudo = 0
    for tag in soup.find_all(["div", "p"], class_=re.compile(r"title|heading|headline", re.I)):
        t = tag.get_text(strip=True)
        if t and len(t) < 100 and not tag.find(["h1", "h2", "h3", "h4"]):
            pseudo += 1

    lists = len(soup.find_all(["ol", "ul"]))
    tables = len(soup.find_all("table"))
    paras = [p.get_text(strip=True) for p in soup.find_all("p") if len(p.get_text(strip=True)) >= 20]
    avg_para = (sum(len(p) for p in paras) // len(paras)) if paras else 0

    # FAQ: h2/h3 文本以问号结尾
    faq_heads = sum(1 for h in soup.find_all(["h2", "h3"]) if h.get_text(strip=True).endswith(("?", "？")))

    # JSON-LD 结构化数据
    ld_types = []
    for s in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            d = json.loads(s.string or "")
            for it in (d if isinstance(d, list) else [d]):
                if isinstance(it, dict) and it.get("@type"):
                    ld_types.append(str(it["@type"]))
        except Exception:
            pass

    # meta 完整度: description + og 标签
    meta_desc = soup.find("meta", attrs={"name": "description"})
    og_count = len(soup.find_all("meta", property=re.compile(r"^og:")))
    meta_desc_len = len(meta_desc.get("content", "")) if meta_desc else 0

    stats_hits = len(re.findall(r"\d+(\.\d+)?\s*[%％]", text))
    domain = urlparse(url).netloc if url else ""
    ext_links = sum(1 for a in soup.find_all("a", href=True)
                    if a["href"].startswith("http") and domain not in a["href"])

    # 评分: 每维 0-2 分 (9 维满分 18) → 折算百分制
    score_items = {
        "标题层级": 2 if (h1 >= 1 and h2 >= 2) else (1 if h2 + h3 >= 3 else (1 if pseudo >= 3 and h2 + h3 == 0 else 0)),
        "结构化内容(列表/表格)": 2 if lists + tables >= 3 else (1 if lists + tables >= 1 else 0),
        "统计数字(含百分比)": 2 if stats_hits >= 5 else (1 if stats_hits >= 1 else 0),
        "FAQ问答体": 2 if faq_heads >= 2 else (1 if faq_heads == 1 else 0),
        "schema.org数据": 2 if len(ld_types) >= 2 else (1 if ld_types else 0),
        "可引用段落(短段)": 2 if 0 < avg_para <= 400 else (1 if avg_para <= 800 else 0),
        "外部引用链接": 2 if ext_links >= 10 else (1 if ext_links >= 3 else 0),
        "内容体量": 2 if words >= 3000 or cjk >= 1500 else (1 if words >= 800 or cjk >= 400 else 0),
        "meta完整度": 2 if (meta_desc_len >= 80 and og_count >= 3) else (1 if meta_desc_len >= 20 or og_count >= 1 else 0),
    }
    return {
        "url": url, "h1": h1, "h2": h2, "h3": h3, "pseudo_heads": pseudo,
        "lists": lists, "tables": tables, "pct_numbers": stats_hits,
        "faq_heads": faq_heads, "ld_types": ld_types[:6],
        "ext_links": ext_links, "avg_para_len": avg_para, "words": words, "cjk": cjk,
        "meta_desc_len": meta_desc_len, "og_tags": og_count,
        "scores": score_items,
        "geo_score": round(sum(score_items.values()) / (2 * len(score_items)) * 100),
    }

async def audit_all(targets):
    browser_cfg = BrowserConfig(headless=True, verbose=False)
    run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
    report = {"time": datetime.datetime.now().isoformat(), "results": []}

    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        for url in targets:
            cfg = run_cfg
            if need_proxy(url):
                cfg = run_cfg.clone(proxy=os.environ.get("HTTPS_PROXY"))
            r = await crawler.arun(url=url, config=cfg)
            if not r.success:
                report["results"].append({"url": url, "error": r.error_message[:120]})
                continue
            a = audit(r.html, r.markdown or "", url)
            a["title"] = (r.metadata or {}).get("title", "")
            report["results"].append(a)
    return report

def show(report):
    ok = [r for r in report["results"] if "error" not in r]
    print(f"{'站点':<46} {'GEO分':>5} {'h2/h3':>6} {'列表':>4} {'%数字':>5} {'FAQ':>4} {'LD':>4} {'词数':>7}")
    print("-" * 88)
    for r in ok:
        host = urlparse(r["url"]).netloc
        print(f"{host + r['url'][r['url'].find(host)+len(host):][:34]:<46} "
              f"{r['geo_score']:>5} {str(r['h2'])+'/'+str(r['h3']):>6} {r['lists']:>4} "
              f"{r['pct_numbers']:>5} {r['faq_heads']:>4} {len(r['ld_types']):>4} {r['words']:>7}")
    for r in report["results"]:
        if "error" in r:
            print(f"  [失败] {r['url']}: {r['error']}")
    if ok:
        best = max(ok, key=lambda r: r["geo_score"])
        print("-" * 88)
        print(f"★ GEO 最优: {urlparse(best['url']).netloc} ({best['geo_score']}分)")
        weak = [k for k, v in best["scores"].items() if v < 2]
        print(f"  它的短板(可作你的差异化机会): {weak or '无'}")

if __name__ == "__main__":
    targets = sys.argv[1:] or DEFAULT_TARGETS
    print(f"GEO 审计目标: {targets}")
    rep = asyncio.run(audit_all(targets))
    show(rep)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "geo_report.json")
    json.dump(rep, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n报告已存: {out}")
