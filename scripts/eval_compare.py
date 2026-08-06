"""
ReCollect - Mock vs Real LLM 对比评估脚本（方案C）

用法：
  python scripts/eval_compare.py --provider qwen
  python scripts/eval_compare.py --provider qwen --task_id eval

原理：
  1. 同一份输入数据（P1 demo 10 条）分别用 Mock 和 Real LLM 跑全链路
     - Mock:  task_id = {base}_mock  (model_override=mock 走启发式)
     - Real:  task_id = {base}_real  (读 .env 中的 provider 配置)
  2. 用已有 scoring.py 对两套结果评分
  3. 输出对比报告到 memory/eval/compare_{timestamp}.json
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import click


def _ensure_p1(task_id: str) -> None:
    """确保 P1 原始数据存在（复用 demo01 的数据）"""
    from config import path_raw, RAW_DIR
    src = RAW_DIR / "demo01_notes.jsonl"
    dst = path_raw(task_id)
    if not dst.exists():
        if src.exists():
            shutil.copy2(src, dst)
        else:
            from pipeline.p1_collect import run as p1_run
            p1_run(task_id=task_id)


def _run_pipeline(task_id: str, use_mock: bool) -> Dict[str, Any]:
    """跑 P2→P3→P5→P4→P6，返回耗时 + 评分"""
    # 清理旧 chroma 索引
    from config import path_chroma
    chroma_path = path_chroma(task_id)
    if chroma_path.exists():
        shutil.rmtree(chroma_path)

    t0 = time.time()

    if use_mock:
        # Mock: 用 model_override="mock" 强制走启发式
        from pipeline.p2_screen import run as p2_run
        from pipeline.p3_summary import run as p3_run
        from pipeline.p5_audit import run as p5_run
        from pipeline.p4_write import run as p4_run
        from pipeline.p6_memory import run as p6_run

        p2_run(task_id=task_id, model_override="mock")
        p3_run(task_id=task_id, model_override="mock", skip_multimodal=True)
        p5_run(task_id=task_id, model_override="mock")
        p4_run(task_id=task_id)
        p6_run(task_id=task_id)
    else:
        # Real LLM: 正常跑（provider 从 .env 读取）
        from pipeline.p2_screen import run as p2_run
        from pipeline.p3_summary import run as p3_run
        from pipeline.p5_audit import run as p5_run
        from pipeline.p4_write import run as p4_run
        from pipeline.p6_memory import run as p6_run

        p2_run(task_id=task_id)
        p3_run(task_id=task_id, skip_multimodal=True)
        p5_run(task_id=task_id)
        p4_run(task_id=task_id)
        p6_run(task_id=task_id)

    elapsed = time.time() - t0

    # 评分
    from memory.eval.scoring import eval_p2, eval_p3, eval_p6, collect_errors
    scores = {
        "p2": eval_p2(task_id),
        "p3": eval_p3(task_id),
        "p6": eval_p6(task_id),
        "errors": collect_errors(task_id),
    }

    return {
        "task_id": task_id,
        "elapsed_s": round(elapsed, 1),
        "scores": scores,
    }


def _fmt_p2(s: Dict) -> str:
    dd = s.get("decision_distribution", {})
    return (f"keep={dd.get('keep',0)} review={dd.get('review',0)} drop={dd.get('drop',0)}"
            f"  ad_recall={s.get('ad_recall','-')}"
            f"  miss_drop={s.get('miss_drop_rate_non_ad','-')}")


def _fmt_p3(s: Dict) -> str:
    return (f"avg_audit={s.get('avg_audit_score','-')}"
            f"  fid={s.get('avg_fidelity','-')}"
            f"  cov={s.get('avg_coverage','-')}"
            f"  cat={s.get('avg_category','-')}"
            f"  pass>=0.8={s.get('pass_rate_ge_08','-')}")


def _fmt_p6(s: Dict) -> str:
    sm = s.get("summary", {})
    return (f"P@k={sm.get('avg_precision_at_k','-')}"
            f"  R@k={sm.get('avg_recall_at_k','-')}"
            f"  RR={sm.get('avg_relevant_rate','-')}")


@click.command()
@click.option("--provider", default="qwen",
              help="真实 LLM provider（qwen/openai/kimi/deepseek）")
@click.option("--task_id", default="eval",
              help="task_id 前缀（会生成 {prefix}_mock 和 {prefix}_real）")
def main(provider: str, task_id: str):
    """Mock vs Real LLM 对比评估"""

    from config import EVAL_DIR

    tid_mock = f"{task_id}_mock"
    tid_real = f"{task_id}_real"

    print("=" * 64)
    print(f"  ReCollect Eval Compare: Mock vs {provider.upper()}")
    print("=" * 64)

    # 确保两边都有 P1 数据
    _ensure_p1(tid_mock)
    _ensure_p1(tid_real)

    # ---- Step 1: Mock ----
    print(f"\n[1/2] Mock provider  →  task_id={tid_mock}")
    mock_res = _run_pipeline(tid_mock, use_mock=True)
    print(f"  Done in {mock_res['elapsed_s']}s")

    # ---- Step 2: Real LLM ----
    print(f"\n[2/2] {provider.upper()} provider  →  task_id={tid_real}")
    real_res = _run_pipeline(tid_real, use_mock=False)
    print(f"  Done in {real_res['elapsed_s']}s")

    # ---- 对比报告 ----
    ms = mock_res["scores"]
    rs = real_res["scores"]

    print("\n" + "=" * 64)
    print("  COMPARISON REPORT")
    print("=" * 64)

    print("\n[P2 筛选]")
    print(f"  Mock:  {_fmt_p2(ms['p2'])}")
    print(f"  Real:  {_fmt_p2(rs['p2'])}")
    print(f"  Errors: Mock={len(ms['errors'])}  Real={len(rs['errors'])}")

    print("\n[P3 归纳（基于 P5 审计）]")
    print(f"  Mock:  {_fmt_p3(ms['p3'])}")
    print(f"  Real:  {_fmt_p3(rs['p3'])}")

    print("\n[P6 检索]")
    print(f"  Mock:  {_fmt_p6(ms['p6'])}")
    print(f"  Real:  {_fmt_p6(rs['p6'])}")

    # 逐 query 对比
    mq = ms["p6"].get("per_query", [])
    rq = rs["p6"].get("per_query", [])
    if mq and rq:
        print("\n  [P6 Per-Query Detail]")
        for m, r in zip(mq, rq):
            print(f"    {m['query_id']}: Mock P={m['precision@k']} R={m['recall@k']}"
                  f"  |  Real P={r['precision@k']} R={r['recall@k']}")
            print(f"      query: {m['query'][:40]}...")

    # Mock 错误案例
    print(f"\n[Mock 错误案例] ({len(ms['errors'])} 条)")
    for e in ms["errors"][:10]:
        print(f"  - {e['note_id']}  gold={e['gold']} pred={e['pred']}"
              f"  ({e.get('gold_type','')})")

    # Real 错误案例
    print(f"\n[Real 错误案例] ({len(rs['errors'])} 条)")
    for e in rs["errors"][:10]:
        print(f"  - {e['note_id']}  gold={e['gold']} pred={e['pred']}"
              f"  ({e.get('gold_type','')})")

    # 写 JSON 报告
    report = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "provider_real": provider,
        "mock": {
            "task_id": tid_mock,
            "elapsed_s": mock_res["elapsed_s"],
            "scores": {k: v for k, v in ms.items() if k != "errors"},
        },
        "real": {
            "task_id": tid_real,
            "elapsed_s": real_res["elapsed_s"],
            "scores": {k: v for k, v in rs.items() if k != "errors"},
        },
        "errors_mock": ms["errors"],
        "errors_real": rs["errors"],
    }
    report_file = EVAL_DIR / f"compare_mock_vs_{provider}_{task_id}.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n[Report] → {report_file}")
    print("=" * 64)


if __name__ == "__main__":
    main()
