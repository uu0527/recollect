"""
Phase 3.4a Smoke Test — 按类别采样 20 cases 验证 Eval Signal

分布:
  summary 4 / source_grounding 4 / decision_support 6 / knowledge_exploration 6

用法:
  python eval/agent/smoke_test.py            # 全部
  python eval/agent/smoke_test.py --stability  # 额外对 3 个 case 做稳定性测试

不修改: dataset / generate_cases / retriever / evaluator / judge / runner
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.agent.context_runner import (  # noqa: E402
    run_case,
    summarize,
    print_table,
    stability_check,
)

EVAL_DIR = Path(__file__).resolve().parent
GENERATED = EVAL_DIR / "generated_cases.json"
RESULTS_DIR = EVAL_DIR / "results"

# 按类别采样配额（共 20）
SAMPLE_QUOTA = {
    "summary": 4,
    "source_grounding": 4,
    "decision_support": 6,
    "knowledge_exploration": 6,
}


def sample_by_category(seed: int = 42) -> list:
    cases = json.loads(GENERATED.read_text(encoding="utf-8"))["cases"]
    by_type: dict = {}
    for c in cases:
        by_type.setdefault(c["case_type"], []).append(c)

    rng = random.Random(seed)
    sampled = []
    for ctype, quota in SAMPLE_QUOTA.items():
        pool = by_type.get(ctype, [])
        sampled.extend(rng.sample(pool, min(quota, len(pool))))
    return sampled


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Phase 3.4a Smoke Test")
    parser.add_argument("--stability", action="store_true", help="对 3 个 case 做稳定性测试")
    parser.add_argument("--seed", type=int, default=42, help="采样随机种子")
    args = parser.parse_args()

    cases = sample_by_category(args.seed)
    print(f"Smoke Test: {len(cases)} cases (seed={args.seed})")
    for c in cases:
        print(f"  {c['id'][:24]} [{c['case_type']}] {c['question'][:36]}")

    results = []
    for case in cases:
        print(f"\n=== {case['id'][:24]} [{case['case_type']}] {case['question'][:36]} ===")
        try:
            r = run_case(case, "both")
            results.append(r)
            for key in ("plain", "context"):
                if key in r:
                    print(f"  {key}: tokens={r[key]['tokens']} scores={r[key]['scores']}")
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {str(exc)[:120]}")

    # Summary + delta
    summary = summarize(results)
    print_table(summary)
    if "plain" in summary and "context" in summary:
        delta = {
            "relevance": round(summary["context"]["relevance"] - summary["plain"]["relevance"], 2),
            "grounding": round(summary["context"]["grounding"] - summary["plain"]["grounding"], 2),
            "answerability": round(summary["context"]["answerability"] - summary["plain"]["answerability"], 2),
            "hallucination": round(
                summary["context"]["hallucination_rate"] - summary["plain"]["hallucination_rate"], 2
            ),
        }
        print("\n=== Context - Plain Delta ===")
        for k, v in delta.items():
            mark = "PASS" if (k == "hallucination" and v <= 0) or (k != "hallucination" and v >= 0.5) else ""
            print(f"  {k:<16} {v:>+6.2f}  {mark}")
        # 验收判断
        ok = delta["relevance"] >= 0.5 and delta["grounding"] >= 0.5
        print(f"\n=== Signal 验收: {'PASS (relevance & grounding delta >= +0.5)' if ok else 'FAIL'} ===")

    # 保存 smoke 结果
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "smoke_test.json"
    out.write_text(
        json.dumps({"seed": args.seed, "summary": summary, "cases": results}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"\nSmoke 结果: {out}")

    # 稳定性测试（3 个 case × 3 次）
    if args.stability:
        print("\n=== 稳定性测试（3 case × 3 runs）===")
        stables = []
        for c in cases[:3]:
            s = stability_check(c)
            stables.append(s)
            dims = ", ".join(f"{k}:std={v['std']}" for k, v in s["dims"].items())
            print(f"  {s['id'][:24]} {dims}")
        stab_out = RESULTS_DIR / "stability_test.json"
        stab_out.write_text(json.dumps(stables, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"稳定性结果: {stab_out}")


if __name__ == "__main__":
    main()
