"""
Failure Analysis 生成器（Phase 3.4a）

从 benchmark 结果中自动识别失败 case 并分类，输出 eval/reports/failure_analysis.md。

分类:
1. Dataset leakage      — query 泄露 title/key_points（title_overlap_ratio > 0.5 或 kp 命中）
2. Retriever miss       — plain 模式下 retriever 未命中预期 knowledge（benchmark 中 plain relevance<=1）
3. Context injection failure — context 模式未注入（context_applied=False）或注入后无提升
4. Judge disagreement   — 同 case 多次评分 variance 过大（std > 0.6）

用法:
  python eval/agent/failure_analysis.py            # 基于 results/*_latest.json
  python eval/agent/failure_analysis.py --smoke    # 基于 smoke_test.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
REPORT_DIR = ROOT / "eval" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def analyze_benchmark(bench_path: Path) -> dict:
    data = json.loads(bench_path.read_text(encoding="utf-8"))
    cases = data.get("cases", [])
    failures = {"leakage": [], "retriever_miss": [], "injection_failure": [], "judge_disagreement": []}

    for c in cases:
        cid = c["id"]
        # 1. leakage: title_overlap_ratio 高（dataset 自带字段）
        if c.get("title_overlap_ratio", 0) > 0.5:
            failures["leakage"].append({"id": cid, "ratio": c["title_overlap_ratio"]})

        plain = c.get("plain", {})
        ctx = c.get("context", {})

        # 2. retriever miss: plain 完全无法回答（relevance<=1 且 grounding<=1）
        if plain:
            ps = plain.get("scores", {})
            if ps.get("relevance", 5) <= 1 and ps.get("grounding", 5) <= 1:
                failures["retriever_miss"].append(
                    {"id": cid, "query": c["question"][:40], "relevance": ps.get("relevance")}
                )

        # 3. injection failure: context_applied=False（应注入却未注入）
        if ctx and c.get("context_applied") is False and c.get("should_inject", True) is not False:
            failures["injection_failure"].append(
                {"id": cid, "query": c["question"][:40]}
            )
        # 或注入后无提升（context relevance <= plain）
        if plain and ctx:
            p_rel = plain.get("scores", {}).get("relevance", 0)
            c_rel = ctx.get("scores", {}).get("relevance", 0)
            if c_rel <= p_rel:
                failures["injection_failure"].append(
                    {"id": cid, "plain_rel": p_rel, "ctx_rel": c_rel, "query": c["question"][:40]}
                )

    return failures


def analyze_stability(stab_path: Path) -> dict:
    data = json.loads(stab_path.read_text(encoding="utf-8"))
    issues = []
    for s in data:
        for dim, v in s["dims"].items():
            if v["std"] > 0.6:
                issues.append({"id": s["id"], "dim": dim, "std": v["std"]})
    return {"judge_disagreement": issues}


def render_md(bench_failures: dict, stab_issues: dict) -> str:
    lines = ["# Failure Analysis (Phase 3.4a)", ""]
    lines.append("> 自动生成，基于 benchmark + stability 结果。")
    lines.append("")

    total = sum(len(v) for v in bench_failures.values())
    lines.append(f"## 总览")
    lines.append(f"- 失败 case 总数: {total}")
    for k, v in bench_failures.items():
        lines.append(f"- {k}: {len(v)}")
    lines.append("")

    labels = {
        "leakage": "Dataset leakage（query 泄露 title/key_points）",
        "retriever_miss": "Retriever miss（plain 模式检索不到预期知识）",
        "injection_failure": "Context injection failure（未注入或注入无提升）",
        "judge_disagreement": "Judge disagreement（多次评分方差过大）",
    }
    for k, v in bench_failures.items():
        lines.append(f"## {k}: {labels[k]}")
        if not v:
            lines.append("- 无")
            lines.append("")
            continue
        for item in v[:10]:
            lines.append(f"- `{item['id']}`: {json.dumps(item, ensure_ascii=False)}")
        if len(v) > 10:
            lines.append(f"- ... 共 {len(v)} 条")
        lines.append("")

    if stab_issues["judge_disagreement"]:
        lines.append("## Judge disagreement（稳定性）")
        for item in stab_issues["judge_disagreement"]:
            lines.append(f"- `{item['id']}` dim={item['dim']} std={item['std']}")
        lines.append("")

    lines.append("## 后续建议")
    lines.append("- 若 retriever_miss 高: 说明 Context Injection 价值最大，应优先保障注入路径")
    lines.append("- 若 leakage 高: 需加强 generate_cases 的 validate_leakage")
    lines.append("- 若 injection_failure 高: 检查 orchestrator._resolve_context 的 fallback 分支")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Failure Analysis Generator")
    parser.add_argument("--bench", default=str(RESULTS_DIR / "generated_latest.json"))
    parser.add_argument("--stability", default=str(RESULTS_DIR / "stability_test.json"))
    args = parser.parse_args()

    bench_path = Path(args.bench)
    stab_path = Path(args.stability)

    bench_failures = analyze_benchmark(bench_path) if bench_path.exists() else {}
    stab_issues = analyze_stability(stab_path) if stab_path.exists() else {"judge_disagreement": []}

    md = render_md(bench_failures, stab_issues)
    out = REPORT_DIR / "failure_analysis.md"
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"\n已写入: {out}")


if __name__ == "__main__":
    main()
