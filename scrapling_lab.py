# -*- coding: utf-8 -*-
"""Scrapling 深度实战实验室 — 四个实验:
1. 反爬检测对比: 普通 HTTP Fetcher vs StealthyFetcher (bot.sannysoft.com 38 项检测)
2. 自适应选择器: 选择器失效后凭元素指纹模糊找回 (网站改版爬虫不崩)
3. 语义定位: find_by_text / find_similar 不写选择器也能采
4. 解析性能: Scrapling (lxml) vs BeautifulSoup 速度对比
"""
import os, sys, time
from urllib.parse import urlparse

sys.stdout.reconfigure(encoding="utf-8")
PROXY = os.environ.get("HTTPS_PROXY")
EXT_PROXY = {"server": PROXY} if PROXY else None  # 境外站走 Clash

from scrapling.fetchers import Fetcher, StealthyFetcher

def banner(n, title):
    print(f"\n{'='*16} 实验 {n}: {title} {'='*16}")

# ---------- 实验 1: 反爬检测对比 ----------
def exp1():
    banner(1, "反爬检测对比 (bot.sannysoft.com)")
    def score(page, label):
        passed = failed = 0
        for row in page.css("table tr"):
            tds = row.css("td")
            if len(tds) < 2:
                continue
            cls = tds[1].attrib.get("class", "")
            if "passed" in cls: passed += 1
            elif "failed" in cls: failed += 1
        total = passed + failed
        print(f"  [{label}] 检测 {total} 项 | 通过 {passed} | 失败 {failed}")
        return passed, failed

    p1 = Fetcher.get("https://bot.sannysoft.com/", stealthy_headers=True, proxy=PROXY)
    a = score(p1, "HTTP Fetcher (curl_cffi)")
    p2 = StealthyFetcher.fetch("https://bot.sannysoft.com/", headless=True, proxy=EXT_PROXY)
    b = score(p2, "StealthyFetcher (frostwork隐身浏览器)")
    print(f"  => 隐身浏览器多通过 {b[0]-a[0]} 项检测")

# ---------- 实验 2: 自适应选择器 ----------
def exp2():
    banner(2, "自适应选择器 (改版后爬虫不崩)")
    Fetcher.configure(adaptive=True)  # 0.5: adaptive 需在页面初始化时启用

    url = "https://github.com/trending/"
    page = Fetcher.get(url, stealthy_headers=True, proxy=PROXY)
    good = page.css("article h2 a", identifier="repo-title", adaptive=True, auto_save=True)
    print(f"  第一轮: 'article h2 a' + identifier='repo-title' 命中 {len(good)} 条 (指纹已存库)")

    # 模拟网站改版: 换一个页面上不存在的坏选择器, 但 identifier 相同 → 凭指纹模糊找回
    page2 = Fetcher.get(url, stealthy_headers=True, proxy=PROXY)
    bad = page2.css("article h4 a", identifier="repo-title", adaptive=True)
    print(f"  第二轮: 坏选择器 'article h4 a' (同 identifier) + adaptive → 找回 {len(bad)} 条")
    if bad:
        print(f"  => 网站改版爬虫不崩, 元素自动找回 ✓  (示例: {bad[0].attrib.get('href','')[:40]})")
    else:
        print("  => 该场景未触发模糊找回 (指纹匹配有距离阈值)")

# ---------- 实验 3: 语义定位 ----------
def exp3():
    banner(3, "语义定位 find_by_text / find_similar")
    page = Fetcher.get("https://github.com/trending/", stealthy_headers=True, proxy=PROXY)
    # find_by_text: 按文本找元素, 不用知道结构
    el = page.find_by_text("skyvern")
    if el:
        print(f"  find_by_text('skyvern') → {el.tag} 元素, href={str(el.attrib.get('href'))[:40]}")
        # find_similar: 从一个元素泛化出全部同类
        sim = el.find_similar()
        print(f"  find_similar() 从这 1 个元素泛化出 {len(sim)+1} 个同类 (整张榜单, 零选择器)")
    else:
        print("  find_by_text 未命中 (榜单变动), 用 find_similar 演示:")
        sample = page.css("article h2 a")[0]
        print(f"  样本 {sample.attrib.get('href','')[:40]} → 泛化 {len(sample.find_similar())+1} 个同类")

# ---------- 实验 4: 解析性能对比 ----------
def exp4():
    banner(4, "解析性能: Scrapling(lxml) vs BeautifulSoup")
    html = Fetcher.get("https://github.com/trending/", stealthy_headers=True, proxy=PROXY).html_content
    from scrapling.parser import Selector
    from bs4 import BeautifulSoup
    N = 20
    t0 = time.perf_counter()
    for _ in range(N):
        s = Selector(html); s.css("a[href]"); s.css("article h2 a")
    t_scrap = (time.perf_counter() - t0) / N * 1000
    t0 = time.perf_counter()
    for _ in range(N):
        b = BeautifulSoup(html, "html.parser"); b.select("a[href]"); b.select("article h2 a")
    t_bs4 = (time.perf_counter() - t0) / N * 1000
    print(f"  页面 {len(html)//1024}KB | Scrapling {t_scrap:.0f}ms/次 | BeautifulSoup {t_bs4:.0f}ms/次 | 快 {t_bs4/t_scrap:.1f}x")

if __name__ == "__main__":
    only = sys.argv[1:] or ["1", "2", "3", "4"]
    exps = {"1": exp1, "2": exp2, "3": exp3, "4": exp4}
    for n in only:
        try:
            exps[n]()
        except Exception as e:
            print(f"  实验 {n} 出错: {type(e).__name__}: {str(e)[:120]}")
    print("\n完成.")
