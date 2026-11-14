# -*- coding: utf-8 -*-
"""EasySpider → LLM 处理管道: 读取 EasySpider 的任务/采集结果, 清洗统计, 可选 LLM 增强。

用法:
  python easyspider_pipeline.py --list                    # 扫描任务清单
  python easyspider_pipeline.py --process <结果.xlsx>     # 处理采集结果
LLM 配置 (环境变量, OpenAI 兼容接口):
  LLM_API_KEY / LLM_BASE_URL (默认智谱 https://open.bigmodel.cn/api/paas/v4) / LLM_MODEL (默认 glm-4-flash)
没有 key 时走规则模式: 去重、清洗、统计摘要, 功能完整可用。
"""
import glob, json, os, re, sys, argparse, datetime

sys.stdout.reconfigure(encoding="utf-8")
ES_ROOT = r"G:\RPA\EasySpider-app\EasySpider_windows_x64"
TASKS = os.path.join(ES_ROOT, "tasks")

# ---------- LLM (可选) ----------
def llm_chat(prompt: str) -> str | None:
    key = os.environ.get("LLM_API_KEY")
    if not key:
        return None
    from openai import OpenAI
    client = OpenAI(
        api_key=key,
        base_url=os.environ.get("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
    )
    model = os.environ.get("LLM_MODEL", "glm-4-flash")
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return r.choices[0].message.content

# ---------- 模式 1: 任务清单 ----------
def list_tasks():
    files = glob.glob(os.path.join(TASKS, "*.json"))
    print(f"共 {len(files)} 个 EasySpider 任务:\n")
    print(f"{'任务ID':<8} {'URL':<42} {'输出参数数':>6}  名称")
    print("-" * 100)
    rows = []
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        tid = os.path.splitext(os.path.basename(f))[0]
        n_params = len(d.get("outputParameters", []))
        rows.append((tid, d.get("url", "?")[:40], n_params, (d.get("name") or "?")[:45]))
    for tid, url, n, name in sorted(rows, key=lambda x: int(x[0]))[:20]:
        print(f"{tid:<8} {url:<42} {n:>6}  {name}")
    print(f"... (只显示前 20, 共 {len(rows)} 个有效任务)")
    return rows

# ---------- 模式 2: 处理采集结果 ----------
def process_result(path: str):
    import pandas as pd
    df = pd.read_excel(path) if path.lower().endswith((".xlsx", ".xls")) else pd.read_csv(path)
    before = len(df)
    df = df.drop_duplicates()
    # 规则统计
    stats = {"原始行数": before, "去重后": len(df), "列": list(df.columns)[:10]}
    num_cols = df.select_dtypes("number").columns.tolist()
    stat_line = df[num_cols].describe().loc[["mean", "min", "max"]].round(2).to_string() if num_cols else "(无数值列)"

    print(f"== 规则处理: {os.path.basename(path)} ==")
    print(f"  行 {before} → 去重 {len(df)} | 列: {stats['列']}")
    print(f"  数值概览:\n{stat_line}\n")

    # LLM 增强 (有 key 才启用)
    sample = df.head(15).to_csv(index=False)
    prompt = f"这是 EasySpider 采集的数据样本。请用中文简要分析: 1)数据内容概览 2)数据质量问题和异常 3)对运营/SEO 的可执行建议。控制在 300 字内。\n\n{sample}"
    print("正在调用 LLM 分析..." if os.environ.get("LLM_API_KEY") else "(未配置 LLM_API_KEY, 跳过 AI 分析)")
    answer = llm_chat(prompt)
    if answer:
        print(f"\n== AI 分析 ==\n{answer}")
    else:
        print("启用方法: set LLM_API_KEY=你的key 后重跑 (兼容 OpenAI/智谱/DeepSeek 等, 用 LLM_BASE_URL/LLM_MODEL 指定)")
        return df, stats

    # 保存结果
    out = path.rsplit(".", 1)[0] + "_processed.xlsx"
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="clean", index=False)
        pd.DataFrame([stats]).to_excel(w, sheet_name="meta", index=False)
    print(f"已保存: {out}")
    return df, stats

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--process", help="采集结果文件 (xlsx/csv)")
    args = ap.parse_args()
    if args.process:
        process_result(args.process)
    else:
        list_tasks()
