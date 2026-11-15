# -*- coding: utf-8 -*-
"""Scrapling 定时监控 v2: 代理池自愈轮换 + MySQL 落库 (SQLite 兜底)

v1 → v2 架构升级:
  1. ProxyPool: 多代理槽位轮换, 失败进冷却、域名亲和粘住成功线路,
     跑得越久越"知道"哪类站点该走哪条线 (自愈路由)
  2. Storage: MySQL 为主库 (crawler 库), 连不上自动降级 SQLite,
     同一套 API, 采集行记录 via=使用的代理槽位 (运营可观测)
  3. proxy_stats 表: 每轮回写代理健康统计, 支撑成功率报表

用法:
  python monitor_watch.py --once                       # 抓一轮 (auto: MySQL 优先, 失败落 SQLite)
  python monitor_watch.py --db sqlite --once           # 强制 SQLite
  python monitor_watch.py --interval 30                # 常驻监控
  python monitor_watch.py --url <url> --sel <选择器>
数据: crawler-lab/monitor.db (SQLite) 或 MySQL crawler 库
"""
import os, sys, time, json, sqlite3, argparse, datetime

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "monitor.db")

DEFAULTS = {"url": "https://github.com/trending/", "sel": "article h2 a"}

# ================= 代理池 =================
class ProxyPool:
    """代理槽位轮换: 失败冷却 + 成功率统计 + 域名亲和 (粘住对某域名成功的线路)"""

    def __init__(self, path=None):
        path = path or os.path.join(HERE, "proxies.json")
        slots = [{"name": "direct", "server": None}]
        if os.path.exists(path):
            try:
                cfg = json.load(open(path, encoding="utf-8"))
                slots = cfg.get("slots", slots)
                self.cooldown_seconds = cfg.get("cooldown_seconds", 300)
            except Exception as e:
                print(f"[ProxyPool] 配置读取失败, 用默认槽位: {e}")
        else:
            self.cooldown_seconds = 300
        self.slots = slots
        self.stats = {s["name"]: {"ok": 0, "fail": 0, "cooldown_until": 0} for s in slots}
        self.affinity = {}          # domain -> 成功过的槽位名
        self._rr = 0

    def acquire(self, preferred=None):
        now = time.time()
        by_name = {s["name"]: s for s in self.slots}
        if preferred and preferred in by_name and self.stats[preferred]["cooldown_until"] <= now:
            return by_name[preferred]
        avail = [s for s in self.slots if self.stats[s["name"]]["cooldown_until"] <= now] or self.slots
        self._rr += 1
        return avail[self._rr % len(avail)]

    def report(self, name, ok):
        st = self.stats[name]
        if ok:
            st["ok"] += 1
        else:
            st["fail"] += 1
            st["cooldown_until"] = time.time() + self.cooldown_seconds

    def summary(self):
        now = time.time()
        return {n: {"ok": s["ok"], "fail": s["fail"], "cooldown": s["cooldown_until"] > now}
                for n, s in self.stats.items()}

    def format_stats(self):
        return {n: f"{s['ok']}✓/{s['fail']}✗" + ("(冷却)" if s["cooldown"] else "")
                for n, s in self.summary().items()}

def grab_with_pool(url, sel, pool):
    """带代理池重试的抓取: 失败换槽位再试, 全灭则抛错。成功即记录域名亲和。"""
    tried, last_err = [], None
    domain = url.split("/")[2] if "://" in url else url
    for _ in range(len(pool.slots)):
        slot = pool.acquire(preferred=pool.affinity.get(domain))
        if slot["name"] in tried:
            continue
        tried.append(slot["name"])
        t0 = time.perf_counter()
        try:
            from scrapling.fetchers import Fetcher
            page = Fetcher.get(url, stealthy_headers=True, proxy=slot.get("server"), timeout=30000)
            ok = page.status == 200
            pool.report(slot["name"], ok)
            if ok:
                dt = time.perf_counter() - t0
                items = [(i, " ".join(el.get_all_text().split())[:120] or el.attrib.get("href", ""),
                          el.attrib.get("href", "")) for i, el in enumerate(page.css(sel), 1)]
                pool.affinity[domain] = slot["name"]
                return items, slot["name"], dt
            last_err = f"{slot['name']}: HTTP {page.status}"
        except Exception as e:
            pool.report(slot["name"], False)
            last_err = f"{slot['name']}: {type(e).__name__} {str(e)[:80]}"
    raise RuntimeError(f"代理池全部槽位失败 | {last_err}")

# ================= 存储层 =================
class MySQLStorage:
    """MySQL 8 主库 (pymysql 直连, 无 ORM)"""

    def __init__(self, host, port, user, password, database):
        import pymysql
        self.conn = pymysql.connect(host=host, port=port, user=user, password=password,
                                    database=database, charset="utf8mb4", autocommit=True)

    def init_schema(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS snapshots(
            ts VARCHAR(32), url VARCHAR(255), rank_no INT, title VARCHAR(200),
            href VARCHAR(255), via VARCHAR(30),
            UNIQUE KEY uq(ts, url, rank_no), KEY idx_url_ts(url, ts))
            ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        c.execute("""CREATE TABLE IF NOT EXISTS changes(
            ts VARCHAR(32), kind VARCHAR(20), detail VARCHAR(255))
            DEFAULT CHARSET=utf8mb4""")
        c.execute("""CREATE TABLE IF NOT EXISTS proxy_stats(
            name VARCHAR(50) PRIMARY KEY, ok INT, fail INT, updated VARCHAR(32))
            DEFAULT CHARSET=utf8mb4""")
        c.close()

    def max_ts(self, url):
        c = self.conn.cursor()
        c.execute("SELECT max(ts) FROM snapshots WHERE url=%s", (url,))
        v = c.fetchone()[0]; c.close(); return v

    def ts_list(self, url):
        c = self.conn.cursor()
        c.execute("SELECT DISTINCT ts FROM snapshots WHERE url=%s ORDER BY ts DESC", (url,))
        v = [r[0] for r in c.fetchall()]; c.close(); return v

    def rows_at(self, url, ts):
        c = self.conn.cursor()
        c.execute("SELECT rank_no,title,href FROM snapshots WHERE url=%s AND ts=%s ORDER BY rank_no", (url, ts))
        v = c.fetchall(); c.close(); return v

    def snapshot_map(self, url, ts):
        c = self.conn.cursor()
        c.execute("SELECT rank_no,title,href FROM snapshots WHERE url=%s AND ts=%s", (url, ts))
        m = {h: (r, t) for r, t, h in c.fetchall()}; c.close(); return m

    def insert_snapshots(self, url, ts, items, via):
        c = self.conn.cursor()
        c.executemany("REPLACE INTO snapshots(ts,url,rank_no,title,href,via) VALUES(%s,%s,%s,%s,%s,%s)",
                      [(ts, url, r, t, h, via) for r, t, h in items])
        c.close()

    def insert_changes(self, ts, logs):
        c = self.conn.cursor()
        c.executemany("INSERT INTO changes VALUES(%s,%s,%s)", [(ts, k, d) for k, d in logs])
        c.close()

    def save_proxy_stats(self, summary):
        c = self.conn.cursor()
        now = datetime.datetime.now().isoformat(timespec="seconds")
        for name, s in summary.items():
            c.execute("REPLACE INTO proxy_stats VALUES(%s,%s,%s,%s)", (name, s["ok"], s["fail"], now))
        c.close()

    def close(self):
        self.conn.close()


class SQLiteStorage:
    """SQLite 兜底库 (与 MySQLStorage 同一套 API); 旧库自动加 via 列"""

    def __init__(self, path=DB):
        self.conn = sqlite3.connect(path)

    def init_schema(self):
        self.conn.execute("""CREATE TABLE IF NOT EXISTS snapshots(
            ts TEXT, url TEXT, rank INTEGER, title TEXT, href TEXT, via TEXT,
            UNIQUE(ts, url, rank))""")
        self.conn.execute("CREATE TABLE IF NOT EXISTS changes(ts TEXT, kind TEXT, detail TEXT)")
        self.conn.execute("""CREATE TABLE IF NOT EXISTS proxy_stats(
            name TEXT PRIMARY KEY, ok INTEGER, fail INTEGER, updated TEXT)""")
        cols = [r[1] for r in self.conn.execute("PRAGMA table_info(snapshots)")]
        if "via" not in cols:
            self.conn.execute("ALTER TABLE snapshots ADD COLUMN via TEXT")
        self.conn.commit()

    def max_ts(self, url):
        return self.conn.execute("SELECT max(ts) FROM snapshots WHERE url=?", (url,)).fetchone()[0]

    def ts_list(self, url):
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT ts FROM snapshots WHERE url=? ORDER BY ts DESC", (url,))]

    def rows_at(self, url, ts):
        return [(r, t, h) for r, t, h in self.conn.execute(
            "SELECT rank,title,href FROM snapshots WHERE url=? AND ts=? ORDER BY rank", (url, ts))]

    def snapshot_map(self, url, ts):
        return {h: (r, t) for r, t, h in self.conn.execute(
            "SELECT rank,title,href FROM snapshots WHERE url=? AND ts=?", (url, ts))}

    def insert_snapshots(self, url, ts, items, via):
        self.conn.executemany("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?,?)",
                              [(ts, url, r, t, h, via) for r, t, h in items])
        self.conn.commit()

    def insert_changes(self, ts, logs):
        self.conn.executemany("INSERT INTO changes VALUES(?,?,?)", [(ts, k, d) for k, d in logs])
        self.conn.commit()

    def save_proxy_stats(self, summary):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        for name, s in summary.items():
            self.conn.execute("REPLACE INTO proxy_stats VALUES(?,?,?,?)", (name, s["ok"], s["fail"], now))
        self.conn.commit()

    def close(self):
        self.conn.close()


def open_storage(mode="auto"):
    """auto: MySQL 优先, 失败打印警告降级 SQLite"""
    if mode in ("auto", "mysql"):
        try:
            st = MySQLStorage(
                host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
                port=int(os.environ.get("MYSQL_PORT", "3306")),
                user=os.environ.get("MYSQL_USER", "root"),
                password=os.environ.get("MYSQL_PASSWORD", "crawler123"),
                database=os.environ.get("MYSQL_DB", "crawler"),
            )
            st.init_schema()
            print("[Storage] MySQL 就绪 (crawler 库)")
            return st
        except Exception as e:
            msg = f"MySQL 连接失败: {str(e)[:100]}"
            if mode == "mysql":
                raise RuntimeError(msg)
            print(f"[Storage] {msg} → 降级 SQLite")
    st = SQLiteStorage()
    st.init_schema()
    print("[Storage] SQLite 就绪 (monitor.db)")
    return st

# ================= 监控主循环 =================
def detect(st, url, items, via):
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    prev_ts = st.max_ts(url)
    prev = st.snapshot_map(url, prev_ts) if prev_ts else {}
    st.insert_snapshots(url, ts, items, via)
    cur = {h: (r, t) for r, t, h in items}
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
    st.insert_changes(ts, logs)
    return ts, bool(prev), logs


def one_round(url, sel, st, pool):
    try:
        items, via, dt = grab_with_pool(url, sel, pool)
    except Exception as e:
        print(f"[监控] 抓取失败: {str(e)[:150]}")
        return
    ts, has_prev, logs = detect(st, url, items, via)
    st.save_proxy_stats(pool.summary())
    print(f"[{ts}] {url} | {len(items)} 条 | {dt:.1f}s | 线路: {via}")
    for k, d in logs:
        print(f"  [{k}] {d}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=DEFAULTS["url"])
    ap.add_argument("--sel", default=DEFAULTS["sel"])
    ap.add_argument("--interval", type=int, default=30, help="分钟")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--db", choices=["auto", "mysql", "sqlite"], default="auto")
    ap.add_argument("--pool-stats", action="store_true", help="结束时打印代理池统计")
    args = ap.parse_args()

    pool = ProxyPool()
    st = open_storage(args.db)
    if args.once:
        one_round(args.url, args.sel, st, pool)
    else:
        print(f"常驻监控 {args.url} 每 {args.interval} 分钟一轮, Ctrl+C 退出")
        try:
            while True:
                one_round(args.url, args.sel, st, pool)
                time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            pass
    if args.pool_stats:
        print("代理池统计:", json.dumps(pool.format_stats(), ensure_ascii=False, indent=2))
    st.close()
