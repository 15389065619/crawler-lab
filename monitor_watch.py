# -*- coding: utf-8 -*-
"""Scrapling 定时监控: 周期抓取目标页, SQLite 存历史, 检测榜单变化 (新上榜/跌出/排名变动)。

用法:
  python monitor_watch.py --once                 # 抓一次并入库 (供任务计划程序定时调用)
  python monitor_watch.py --interval 30          # 常驻模式, 每 30 分钟一轮
  python monitor_watch.py --url <url> --sel 'article h2 a'   # 自定义目标
数据: crawler-lab/monitor.db
"""
import os, sqlite3, sys, time, argparse, datetime

sys.stdout.reconfigure(encoding="utf-8")
from scrapling.fetchers import Fetcher

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "monitor.db")
PROXY_HOSTS = ("github.com", "news.ycombinator.com")

DEFAULTS = {
    "url": "https://github.com/trending/",
    "sel": "article h2 a",
}

def init_db():
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE IF NOT EXISTS snapshots(
        ts TEXT, url TEXT, rank INTEGER, title TEXT, href TEXT,
        UNIQUE(ts, url, rank))""")
    con.execute("""CREATE TABLE IF NOT EXISTS changes(
        ts TEXT, kind TEXT, detail TEXT)""")
    return con

def proxy_for(url):
    return os.environ.get("HTTPS_PROXY") if any(h in url for h in PROXY_HOSTS) else None

def grab_once(url, sel):
    from scrapling.fetchers import Fetcher
    page = Fetcher.get(url, stealthy_headers=True, proxy=proxy_for(url), timeout=30000)
    items = []
    for i, el in enumerate(page.css(sel), 1):
        title = " ".join(el.get_all_text().split()) or el.attrib.get("href", "")
        items.append((i, title[:120], el.attrib.get("href", "")))
    return items

def detect(con, url, items):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    prev_ts = con.execute("SELECT max(ts) FROM snapshots WHERE url=?", (url,)).fetchone()[0]
    prev = {}
    if prev_ts:
        prev = {h: (r, t) for r, t, h in con.execute(
            "SELECT rank,title,href FROM snapshots WHERE url=? AND ts=?", (url, prev_ts))}
    cur = {h: (r, t) for r, t, h in items}
    con.executemany("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?)",
                    [(ts, url, r, t, h) for r, t, h in items])
    logs = []
    for h, (r, t) in cur.items():
        if h not in prev:
            logs.append(("新上榜", f"#{r} {t}"))
        elif prev[h][0] != r:
            logs.append(("排名变动", f"{t}: #{prev[h][0]} → #{r}"))
    if prev:
        for h, (r, t) in prev.items():
            if h not in cur:
                logs.append(("跌出榜", f"(原#{r}) {t}"))
    con.executemany("INSERT INTO changes VALUES(?,?,?)",
                    [(ts, k, d) for k, d in logs])
    con.commit()
    return ts, prev_ts is not None, logs

def one_round(url, sel, con):
    t0 = time.perf_counter()
    try:
        items = grab_once(url, sel)
    except Exception as e:
        print(f"[监控] 抓取失败: {str(e)[:150]}")
        return
    dt = time.perf_counter() - t0
    ts, has_prev, logs = detect(con, url, items)
    print(f"[{ts}] {url} | {len(items)} 条 | {dt:.1f}s")
    if not has_prev:
        print("  (首次抓取, 建立基线)")
    for k, d in logs:
        print(f"  [{k}] {d}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULTS["url"])
    ap.add_argument("--sel", default=DEFAULTS["sel"])
    ap.add_argument("--interval", type=int, default=30, help="分钟")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    con = init_db()
    if args.once:
        one_round(args.url, args.sel, con)
    else:
        print(f"常驻监控 {args.url} 每 {args.interval} 分钟一轮, Ctrl+C 退出")
        while True:
            one_round(args.url, args.sel, con)
            time.sleep(args.interval * 60)
