# -*- coding: utf-8 -*-
"""飞书群机器人推送: 把情报日报发到飞书群。

配置读取顺序:
  1. 环境变量 FEISHU_WEBHOOK (可选 FEISHU_SECRET, 开了签名校验的机器人用)
  2. crawler-lab/feishu_config.json  {"webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/xxx", "secret": ""}

Webhook 获取方法: 飞书群 → 右上角设置 → 群机器人 → 添加自定义机器人 → 复制 Webhook 地址
"""
import os, json, time, hashlib, hmac, base64, sys, datetime, re

HERE = os.path.dirname(os.path.abspath(__file__))

def load_config():
    hook = os.environ.get("FEISHU_WEBHOOK")
    secret = os.environ.get("FEISHU_SECRET", "")
    keyword = os.environ.get("FEISHU_KEYWORD", "")
    if not hook:
        cfg_file = os.path.join(HERE, "feishu_config.json")
        if os.path.exists(cfg_file):
            d = json.load(open(cfg_file, encoding="utf-8"))
            hook, secret = d.get("webhook", ""), d.get("secret", "")
            keyword = keyword or d.get("keyword", "")
    return hook, secret, keyword

def sign(secret: str, ts: int) -> str:
    key = f"{ts}\n{secret}".encode("utf-8")
    return base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()

def send_text(text: str) -> dict:
    """发送纯文本消息, 返回飞书响应 dict; 自动带上机器人关键词"""
    hook, secret, keyword = load_config()
    if not hook:
        return {"error": "未配置 webhook (环境变量 FEISHU_WEBHOOK 或 feishu_config.json)"}
    if keyword and keyword not in text:
        text = f"【{keyword}】" + text
    payload = {"msg_type": "text", "content": {"text": text}}
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = sign(secret, ts)
    import requests
    r = requests.post(hook, json=payload, timeout=15)
    return r.json()

def digest_from_report(report_path: str) -> str:
    """把日报 markdown 压缩成飞书消息摘要"""
    md = open(report_path, encoding="utf-8").read()
    ts = datetime.datetime.now().strftime("%m-%d %H:%M")
    # 抽取仓库行和选题行
    repo_lines = [l.strip() for l in md.splitlines() if l.startswith("### ") or l.startswith("- 高频词") or l.startswith("- 结构")]
    topics = [l.strip() for l in md.splitlines() if re.match(r"^\d+\. ", l)]
    es = next((l.strip() for l in md.splitlines() if l.startswith("- ") and ("EasySpider" in l or "xlsx" in l or "任务" in l)), "")
    msg = [f"📊 内容情报站日报 [{ts}]", ""]
    for l in repo_lines:
        if l.startswith("### "):
            msg.append("")
            msg.append(l.replace("### ", "🔹 "))
        else:
            msg.append("  " + l.replace("- ", ""))
    if topics:
        msg += ["", "💡 选题建议:"]
        msg += ["  " + t for t in topics[:3]]
    if es:
        msg += ["", "🕷 " + es.replace("- ", "")]
    return "\n".join(msg)

def send_report(report_path: str) -> dict:
    return send_text(digest_from_report(report_path))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        resp = send_report(sys.argv[1])
    else:
        resp = send_text("✅ 内容情报站测试消息: 通道连通!")
    print(json.dumps(resp, ensure_ascii=False))
