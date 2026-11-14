# -*- coding: utf-8 -*-
"""Crawlab Demo 爬虫: 抓博客园首页文章标题 (纯标准库, 输出 result.csv)"""
import urllib.request, re, csv

html = urllib.request.urlopen("https://www.cnblogs.com/", timeout=20).read().decode("utf-8", "ignore")
titles = re.findall(r'class="post-item-title"[^>]*>([^<]+)</a>', html)
print(f"抓到 {len(titles)} 篇文章标题")
with open("result.csv", "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["title"])
    for t in titles:
        w.writerow([t.strip()])
print("result.csv 已生成")
