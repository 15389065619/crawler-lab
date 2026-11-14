# -*- coding: utf-8 -*-
"""Crawl4AI demo: 抓取页面并输出 LLM 友好的 Markdown"""
import asyncio, os, time, sys
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

TARGET = sys.argv[1] if len(sys.argv) > 1 else "https://news.ycombinator.com/"
PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

async def main():
    browser_cfg = BrowserConfig(
        headless=True, verbose=False,
        proxy=PROXY,  # 透传 Clash 代理,否则国内网络直连被 reset
    )
    run_cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)

    t0 = time.perf_counter()
    async with AsyncWebCrawler(config=browser_cfg) as crawler:
        result = await crawler.arun(url=TARGET, config=run_cfg)
        dt = time.perf_counter() - t0

        if not result.success:
            print(f"[FAIL] {result.error_message}")
            return
        md = result.markdown or ""
        print(f"[Crawl4AI] {TARGET}")
        print(f"耗时 {dt:.1f}s | Markdown {len(md)} 字符 | 链接数 {len(result.links.get('internal', []))}")
        print("-" * 60)
        print(md[:800])

asyncio.run(main())
