# -*- coding: utf-8 -*-
"""Cloudflare 突破实战 (教学靶场: scrapingcourse.com/cloudflare, Apify 官方爬虫练习场)

对照组设计:
  A. 普通 HTTP Fetcher        → 预期 403 被拦
  B. 隐身浏览器 (不破盾)       → 预期停在 'Just a moment...' 挑战页
  C. 隐身浏览器 + solve_cloudflare → 预期突破, 拿到真实内容
"""
import os, sys, time

sys.stdout.reconfigure(encoding="utf-8")
PROXY = os.environ.get("HTTPS_PROXY")
EXT_PROXY = {"server": PROXY} if PROXY else None
TARGET = "https://www.scrapingcourse.com/cloudflare-challenge"

def peek(page, label, t0):
    dt = time.perf_counter() - t0
    title = (page.find("title").text or "").strip() if page.find("title") else "(无)"
    h2 = page.find("h2")
    h2_text = " ".join((h2.text or "").split()) if h2 else "(无 h2)"
    print(f"  [{label}] 状态 {page.status} | 耗时 {dt:.0f}s")
    print(f"     页面标题: {title}")
    print(f"     h2 内容 : {h2_text[:60]}")
    return title, h2_text

def main():
    from scrapling.fetchers import Fetcher, StealthyFetcher

    print(f"目标: {TARGET}\n")

    # A. 普通 HTTP
    print("== A. 普通 HTTP Fetcher (curl_cffi) ==")
    try:
        t0 = time.perf_counter()
        page = Fetcher.get(TARGET, stealthy_headers=True, proxy=PROXY)
        peek(page, "A", t0)
    except Exception as e:
        print(f"     直接异常: {type(e).__name__}: {str(e)[:100]}")

    # B. 隐身浏览器但不破盾
    print("\n== B. StealthyFetcher (solve_cloudflare=False) ==")
    t0 = time.perf_counter()
    page = StealthyFetcher.fetch(TARGET, headless=True, proxy=EXT_PROXY, timeout=90000)
    peek(page, "B", t0)

    # C. 隐身浏览器 + 自动破盾
    print("\n== C. StealthyFetcher (solve_cloudflare=True, 等 CF 挑战自动通过) ==")
    t0 = time.perf_counter()
    page = StealthyFetcher.fetch(
        TARGET, headless=True, proxy=EXT_PROXY,
        solve_cloudflare=True, timeout=180000,
    )
    title, h2 = peek(page, "C", t0)
    print("\n== 战报 ==")
    if "bypass" in (title + h2).lower() or "challenge" in h2.lower():
        print("  ★ 突破成功! 拿到了被 CF 保护的页面真实内容")
    else:
        print("  本次未确认突破标记 (CF 挑战可能变化, 重跑一次)")

if __name__ == "__main__":
    main()
