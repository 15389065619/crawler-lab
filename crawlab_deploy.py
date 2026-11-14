# -*- coding: utf-8 -*-
"""把 crawler-lab 的采集脚本接入 Crawlab 平台: 建爬虫 → 传文件 → 跑任务 → 收日志"""
import json, sys, time, urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://localhost:8090/api"

def login():
    req = urllib.request.Request(BASE + "/login", method="POST",
                                 data=json.dumps({"username": "admin", "password": "admin"}).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=15).read())["data"]

TOKEN = login()

def api(method, path, payload=None, raw=False):
    req = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(payload).encode() if payload else None,
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},  # Crawlab 不认 Bearer 前缀
    )
    try:
        body = urllib.request.urlopen(req, timeout=30).read().decode()
        return body if raw else json.loads(body)
    except urllib.error.HTTPError as e:
        return {"http_error": e.code, "body": e.read().decode()[:200]}

SPIDER_CODE = '''import urllib.request, re, csv
html = urllib.request.urlopen('https://www.cnblogs.com/', timeout=20).read().decode('utf-8', 'ignore')
titles = re.findall(r'class="post-item-title"[^>]*>([^<]+)</a>', html)
print(f"抓到 {len(titles)} 篇文章标题")
with open('result.csv', 'w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f); w.writerow(['title'])
    for t in titles:
        w.writerow([t])
print('result.csv 已生成')
'''

# 1. 建爬虫
r = api("POST", "/spiders", {"name": "cnblogs-demo", "display_name": "博客园标题采集 Demo",
                              "cmd": "python3 cnblogs_spider.py", "mode": "all"})
sid = (r.get("data") or {}).get("_id") if isinstance(r.get("data"), dict) else None
if not sid:
    print("建爬虫响应:", json.dumps(r, ensure_ascii=False)[:300]); sys.exit(1)
print(f"✓ 爬虫已建: cnblogs-demo (id={sid})")

# 2. 传脚本
r = api("POST", f"/spiders/{sid}/files/save", {"path": "cnblogs_spider.py", "data": SPIDER_CODE})
print("✓ 脚本已上传" if r.get("status") == "ok" else f"上传响应: {json.dumps(r, ensure_ascii=False)[:200]}")

# 3. 触发任务
r = api("POST", "/tasks", {"spider_id": sid})
tid = (r.get("data") or {}).get("_id") if isinstance(r.get("data"), dict) else None
print(f"✓ 任务已触发: {tid}" if tid else f"任务响应: {json.dumps(r, ensure_ascii=False)[:300]}")

# 4. 轮询状态
for i in range(12):
    time.sleep(3)
    st = api("GET", f"/tasks/{tid}")
    status = (st.get("data") or {}).get("status")
    print(f"  [{i*3}s] status = {status}")
    if status in ("finished", "error", "cancelled"):
        break

# 5. 日志
r = api("GET", f"/tasks/{tid}/logs")
logs = r.get("data") or ""
print("--- 任务日志 ---")
print(logs if isinstance(logs, str) else json.dumps(logs, ensure_ascii=False)[:500])
