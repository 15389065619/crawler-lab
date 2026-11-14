# -*- coding: utf-8 -*-
"""Scrapling 0.5 demo: HTTP 抓取 + 自适应选择器 + 隐身浏览器,对比 Crawl4AI"""
import os, sys, time
from scrapling.fetchers import Fetcher, StealthyFetcher

TARGET = sys.argv[1] if len(sys.argv) > 1 else "https://github.com/trending/"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
SEL = 'article h2 a' if 'github.com' in TARGET else '.titleline > a'

# ---- 1. 普通 HTTP 抓取 (curl_cffi 模拟浏览器 TLS 指纹) ----
t0 = time.perf_counter()
page = Fetcher.get(TARGET, stealthy_headers=True, proxy=PROXY)
dt = time.perf_counter() - t0
print(f"[Fetcher] 状态 {page.status} | 耗时 {dt:.2f}s | 标题: {page.find('title').text}")
titles = page.css(SEL)
print(f"  选择器 '{SEL}' 抓到 {len(titles)} 条,前 3 条:")
for t in titles[:3]:
    name = " ".join(t.get_all_text().split()) or t.attrib.get("href", "?")
    print(f"   - {name[:60]}")
print("-" * 60)

# ---- 2. find_similar: 给一个元素,自动找页面所有同类 (快速泛化采集规则) ----
sample = titles[0]
siblings = sample.find_similar()
print(f"[find_similar] 从 1 个样本泛化出 {len(siblings) + 1} 个同类元素 (无需写选择器)")

# ---- 3. 自适应选择器: selector 失效时按元素指纹重新定位 ----
hits = page.css('article h2 a', adaptive=True, auto_save=True)
print(f"[adaptive] 自适应选择器命中 {len(hits)} 条 (存入本地指纹库,网站改版后仍可用)")
print("-" * 60)

# ---- 4. 页面转 Markdown (对比 Crawl4AI 的输出) ----
md = page.markdown()
print(f"[markdown] 本页 Markdown {len(md)} 字符,预览:")
print("  " + " ".join(md.split())[:200])
print("-" * 60)

# ---- 5. 隐身浏览器抓取 (frostwork 反指纹,应对 Cloudflare 等) ----
print("[StealthyFetcher] 启动隐身浏览器...")
t0 = time.perf_counter()
stealth_page = StealthyFetcher.fetch(
    TARGET, headless=True,
    proxy={"server": PROXY} if PROXY else None,
)
dt = time.perf_counter() - t0
st_titles = stealth_page.css(SEL)
print(f"[StealthyFetcher] 状态 {stealth_page.status} | 耗时 {dt:.1f}s | 命中 {len(st_titles)} 条")
