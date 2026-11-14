# -*- coding: utf-8 -*-
"""feapder BatchSpider demo: GitHub Trending 分页采集 (任务表驱动 + Redis 调度 + 断点续爬)"""
import csv
import os

import feapder
from feapder import ArgumentParser

PROXY = os.environ.get("HTTPS_PROXY")  # github 需走 Clash


class TrendingBatchSpider(feapder.BatchSpider):
    __custom_setting__ = dict(
        REDISDB_IP_PORTS="localhost:6380",
        REDISDB_USER_PASS="",
        REDISDB_DB=0,
        MYSQL_IP="127.0.0.1",
        MYSQL_PORT=3306,
        MYSQL_DB="crawler",
        MYSQL_USER_NAME="root",
        MYSQL_USER_PASS="crawler123",
    )

    def download_midware(self, request):
        if PROXY:
            request.proxies = {"http": PROXY, "https": PROXY}
        return request

    def start_requests(self, task):
        # task = 任务表里的一行: {"id", "url", "batch_number"}
        yield feapder.Request(task["url"], download_midware=self.download_midware,
                              task_id=task["id"])

    def parse(self, request, response):
        names = []
        for a in response.xpath('//article//h2/a'):
            name = " ".join("".join(a.xpath(".//text()").extract()).split())
            if name:
                names.append(name)
        page = request.url[-1] if request.url[-1].isdigit() else "1"
        print(f"第{page}页抓到 {len(names)} 个仓库")
        csv_path = "trending_result.csv"
        new_file = not os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["page", "repo"])
            for n in names:
                w.writerow([page, n])
        print(f"  已追加到 {csv_path}")
        # BatchSpider 设计约定: 任务完成必须显式 yield 状态回调, 否则 master 会视为丢失任务反复重派
        yield lambda: self.update_task_state(request.task_id, 1)


if __name__ == "__main__":
    import sys
    spider = TrendingBatchSpider(
        redis_key="trending:batch",           # Redis 调度队列
        task_table="trending_tasks",          # MySQL 任务表
        task_keys=["id", "url"],              # 任务字段
        task_state="state",                   # 状态字段 (0待处理/1完成)
        batch_record_table="trending_batch_record",
        batch_name="GitHub Trending 分页采集",
        batch_interval=1,                     # 批次周期: 1 天
    )

    # 绕开 terminal-layout (无 TTY 环境会静默退出), 直调方法
    if "--start_master" in sys.argv:
        spider.start_monitor_task()           # master: 把任务表数据灌入 redis 队列
    elif "--update_task" in sys.argv:
        spider.update_task_batch()
    else:
        spider.start()                        # worker: 从 redis 领任务执行
