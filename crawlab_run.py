# -*- coding: utf-8 -*-
"""Crawlab 任务运行器: 用官方 /tasks/run 端点触发并轮询 (响应 data 形态多样, 做了兼容)"""
import json, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://localhost:8090/api"
SID = sys.argv[1] if len(sys.argv) > 1 else "6af8b3669ac8fc7dc42098a4"
CMD = sys.argv[2] if len(sys.argv) > 2 else "python3 cnblogs_spider.py"


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


r = call("POST", "/tasks/run", {"spider_id": SID, "cmd": CMD})
tid = get_id(r)
print("任务:", tid) if tid else print("响应:", json.dumps(r, ensure_ascii=False)[:250])
if not tid:
    raise SystemExit(1)

status = ""
for i in range(12):
    time.sleep(3)
    d = call("GET", f"/tasks/{tid}").get("data")
    if isinstance(d, list):
        d = d[0] if d else {}
    if isinstance(d, dict):
        status = d.get("status") or ""
        print(f"  [{i*3}s] status={status!r} exit={d.get('exit_code')!r}")
    if status in ("finished", "error", "cancelled"):
        break

r = call("GET", f"/tasks/{tid}/logs")
logs = r.get("data")
print("--- 任务日志 ---")
print(logs if isinstance(logs, str) else json.dumps(logs, ensure_ascii=False)[:800])
