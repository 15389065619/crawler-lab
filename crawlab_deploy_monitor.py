# -*- coding: utf-8 -*-
"""把 monitor_watch 注册进 Crawlab: 容器版代理配置 + MySQL 环境包装器"""
import json, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://localhost:8090/api"


def login():
    req = urllib.request.Request(BASE + "/login", method="POST",
                                 data=json.dumps({"username": "admin", "password": "admin"}).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())["data"]


T = login()
H = {"Authorization": T, "Content-Type": "application/json"}


def call(method, path, payload=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(payload).encode() if payload else None, headers=H)
    try:
        return json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as e:
        return {"err": e.code, "body": e.read().decode()[:200]}


def get_id(r):
    d = r.get("data")
    if isinstance(d, str):
        return d
    if isinstance(d, dict):
        return d.get("_id")
    if isinstance(d, list) and d:
        return d[0] if isinstance(d[0], str) else d[0].get("_id")
    return None


RUN_MONITOR = '''# -*- coding: utf-8 -*-
"""Crawlab 容器环境包装器: 注入宿主机 MySQL/代理地址后运行监控一轮"""
import os, sys, json

os.environ.setdefault("MYSQL_HOST", "host.docker.internal")
os.environ.setdefault("MYSQL_PORT", "3306")
os.environ.setdefault("MYSQL_USER", "root")
os.environ.setdefault("MYSQL_PASSWORD", "crawler123")
os.environ.setdefault("MYSQL_DB", "crawler")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor_watch as mw

st = mw.open_storage("mysql")
pool = mw.ProxyPool()
mw.one_round(mw.DEFAULTS["url"], mw.DEFAULTS["sel"], st, pool)
print("代理池统计:", json.dumps(pool.format_stats(), ensure_ascii=False))
st.close()
'''

PROXIES = {
    "slots": [
        {"name": "direct", "server": None, "note": "直连(国内站)"},
        {"name": "clash", "server": "http://host.docker.internal:7897", "note": "宿主机 Clash"},
    ],
    "cooldown_seconds": 300,
}

# 1. 建爬虫
r = call("POST", "/spiders", {"name": "trending-monitor", "display_name": "Trending 榜单监控(代理池+MySQL)",
                              "cmd": "python3.10 run_monitor.py", "mode": "all",
                              "col_id": None, "col_name": "trending_snapshots"})
sid = get_id(r)
print("爬虫:", sid) if sid else (print("建爬虫响应:", json.dumps(r, ensure_ascii=False)[:250]), sys.exit(1))

# 2. 传三个文件
monitor_code = open("monitor_watch.py", encoding="utf-8").read()
for path, data in [
    ("monitor_watch.py", monitor_code),
    ("proxies.json", json.dumps(PROXIES, ensure_ascii=False, indent=2)),
    ("run_monitor.py", RUN_MONITOR),
]:
    r = call("POST", f"/spiders/{sid}/files/save", {"path": path, "data": data})
    print(f"文件 {path}:", "✓" if r.get("status") == "ok" else json.dumps(r, ensure_ascii=False)[:120])

# 3. 触发任务
r = call("POST", "/tasks/run", {"spider_id": sid, "cmd": "python3.10 run_monitor.py"})
tid = get_id(r)
print("任务:", tid) if tid else (print("任务响应:", json.dumps(r, ensure_ascii=False)[:250]), sys.exit(1))

# 4. 轮询
status = ""
for i in range(15):
    time.sleep(3)
    d = call("GET", f"/tasks/{tid}").get("data")
    if isinstance(d, list):
        d = d[0] if d else {}
    status = (d or {}).get("status") or status
    print(f"  [{i*3}s] {status!r}")
    if status in ("finished", "error", "cancelled"):
        break

r = call("GET", f"/tasks/{tid}/logs")
logs = r.get("data")
print("--- 任务日志 ---")
print(logs if isinstance(logs, str) else json.dumps(logs, ensure_ascii=False)[:800])
print("spider_id:", sid, "| task_id:", tid)
