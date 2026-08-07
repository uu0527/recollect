#!/usr/bin/env python3
"""
真实数据全链路运行（P2 → P3 → P5 → P4 → P6，全部真实 LLM，不 mock）

用法：
    python scripts/run_full_pipeline.py <task_id>

前置：
- .env 已配置 DeepSeek/Qwen/Zhipu 真实 Key + 飞书 4 项
- data/01_raw/{task_id}_notes.jsonl 存在且有效率 >= 80%

输出：每阶段耗时/模型/成功失败数，最终飞书写入数
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

import json  # noqa: E402
import os  # noqa: E402


def load_env_state():
    """返回当前启用配置（不打印 key）"""
    return {
        "P2": os.environ.get("RECOLLECT_P2_PROVIDER", "?"),
        "P3": os.environ.get("RECOLLECT_P3_PROVIDER", "?"),
        "P5": os.environ.get("RECOLLECT_P5_PROVIDER", "?"),
        "feishu_mock": os.environ.get("FEISHU_APP_ID", "") == "",
    }


def main(task_id: str) -> int:
    from config import FEISHU

    # ---- 前置检查 ----
    raw = ROOT / "data" / "01_raw" / f"{task_id}_notes.jsonl"
    if not raw.exists():
        print(f"[ERROR] 输入不存在: {raw}")
        return 2

    # 有效性检查（>=80% 才跑）
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_jsonl import check as check_jsonl

    if check_jsonl(str(raw)) != 0:
        print("\n[ABORT] 有效率 < 80%，不运行全链路")
        return 3

    env = load_env_state()
    print("=" * 56)
    print("ReCollect 真实全链路运行")
    print("=" * 56)
    print(f"Task: {task_id} | 输入: {raw.name}")
    print(f"Provider: P2={env['P2']} P3={env['P3']} P5={env['P5']}")
    print(f"飞书写入: {'Mock(未配飞书)' if env['feishu_mock'] else 'Real'}")

    results = {}

    # ---- P2 筛选 ----
    from pipeline.p2_screen import run as p2

    t0 = time.time()
    print(f"\n--- P2 筛选 ({env['P2']}) ---")
    p2(task_id)
    results["P2"] = {"sec": round(time.time() - t0, 1)}

    # ---- P3 归纳 ----
    from pipeline.p3_summary import run as p3

    t0 = time.time()
    print(f"\n--- P3 归纳 ({env['P3']}) ---")
    p3(task_id)
    results["P3"] = {"sec": round(time.time() - t0, 1)}

    # ---- P5 审计 ----
    from pipeline.p5_audit import run as p5

    t0 = time.time()
    print(f"\n--- P5 审计 ({env['P5']}) ---")
    p5(task_id)
    results["P5"] = {"sec": round(time.time() - t0, 1)}

    # ---- P4 飞书写入 ----
    from pipeline.p4_write import run as p4

    t0 = time.time()
    print(f"\n--- P4 飞书写入 ({'Real' if not FEISHU['use_mock'] else 'Mock'}) ---")
    p4(task_id, use_mock=False)
    results["P4"] = {"sec": round(time.time() - t0, 1)}

    # ---- 汇总 ----
    print("\n" + "=" * 56)
    print("运行结果汇总")
    print("=" * 56)
    for stage, r in results.items():
        print(f"  {stage}: {r['sec']}s")
    # 飞书写入数
    rec_path = ROOT / "data" / "04_write" / f"{task_id}_write_records.jsonl"
    if rec_path.exists():
        recs = [json.loads(l) for l in rec_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        written = sum(1 for r in recs if r.get("write_success"))
        print(f"  飞书写入记录: {written}/{len(recs)} 成功")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/run_full_pipeline.py <task_id>")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
