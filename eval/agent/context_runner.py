"""
Context-aware Agent Eval Runner (Phase 3.4a)

验证 Knowledge Context Injection 是否提升 Agent 质量，并评估 Context Router 决策。

功能:
- 分层加载: generated_cases.json / router_cases.json / regression_cases.json / context_cases.json(golden)
- --strategy: plain | context（比较 baseline vs injection）
- answerability judge 维度（模型是否知道何时拒答）
- router 决策评估: should_inject vs actual_inject → accuracy
- 稳定性测试: --stability N 同 case 跑 N 次统计 score variance
- 报告输出: eval/agent/results/

用法:
  python eval/agent/context_runner.py --dataset generated
  python eval/agent/context_runner.py --dataset router
  python eval/agent/context_runner.py --dataset generated --strategy context
  python eval/agent/context_runner.py --dataset generated --stability 3 --limit 5
  python eval/agent/context_runner.py --case <id>

数据记录: 复用 backend evaluator → eval/agent/agent_runs.jsonl（含 mode/context_applied）
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

DATASETS = {
    "golden": EVAL_DIR / "context_cases.json",
    "generated": EVAL_DIR / "generated_cases.json",
    "router": EVAL_DIR / "router_cases.json",
    "regression": EVAL_DIR / "regression_cases.json",
}


def load_cases(dataset: str) -> List[Dict]:
    path = DATASETS.get(dataset)
    if not path or not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["cases"]


# ============================================================
# Agent 调用（复用 orchestrator，不改推理逻辑）
# ============================================================
def call_agent(question: str, session_id: str, context: Dict | None) -> Dict:
    from backend.agent.orchestrator import AgentOrchestrator

    orch = AgentOrchestrator()
    return orch.handle(query=question, session_id=session_id, context=context)


# ============================================================
# LLM-as-judge 评分（含 answerability）
# ============================================================
JUDGE_PROMPT = (
    "你是评估器。给定: 知识上下文(knowledge context)、用户问题、Agent 回答。"
    "请打分 1-5（整数）并判断是否幻觉。\n"
    "指标:\n"
    "1. relevance: 回答是否解决用户问题(1-5)\n"
    "2. grounding: 回答是否基于给定 knowledge context(1-5)；无 context 时 grounding=1\n"
    "3. hallucination: 是否出现'未标注来源的编造事实'(是/否)。\n"
    "   注意: 若回答明确说明'基于通用知识补充/不在收藏中'，补充内容不算幻觉=false。\n"
    "   只有把 knowledge 未提供的具体事实当作收藏内容陈述时，才判定为 true。\n"
    "4. answerability: 评估模型是否知道何时该作答/何时该说明知识不足(1-5)。\n"
    "   5=知识充分且正确作答; 4=知识部分充分,说明限制后合理回答;\n"
    "   3=知识不足但补充通用信息(已标注),可接受; 2=知识不足仍编造细节;\n"
    "   1=知识充分却错误拒答。\n"
    "只输出 JSON: {\"relevance\":1,\"grounding\":1,\"hallucination\":false,\"answerability\":4}\n"
)


def judge_answer(context_text: str, question: str, answer: str) -> Dict[str, Any]:
    """用 LLM 对回答打分（失败返回默认分，不阻断）"""
    try:
        from pipeline._llm.router import get_stage_provider

        provider = get_stage_provider(
            stage="chat", task_id="eval_judge", task_type="qa", text=question
        )
        user = (
            f"Knowledge Context:\n{context_text or '(无)'}\n\n"
            f"Question: {question}\n\nAnswer: {answer[:800]}"
        )
        raw = provider.json_complete(
            JUDGE_PROMPT,
            user,
            schema={"required": ["relevance", "grounding", "hallucination", "answerability"]},
        )
        return {
            "relevance": int(raw.get("relevance", 1)),
            "grounding": int(raw.get("grounding", 1)),
            "hallucination": bool(raw.get("hallucination", True)),
            "answerability": int(raw.get("answerability", 1)),
        }
    except Exception as exc:
        print(f"  [judge] WARNING: 评分失败，用默认值: {type(exc).__name__}")
        return {"relevance": 1, "grounding": 1, "hallucination": True, "answerability": 1}


def build_context_text(knowledge_id: str) -> str:
    """构造 judge 展示用的 knowledge context 文本"""
    from collector.context_store.adapters import get_adapter

    card = get_adapter().get_knowledge_by_note_id(knowledge_id)
    if not card:
        return ""
    parts = [f"Title: {card.get('title','')}", f"Summary: {card.get('tldr','')}"]
    for kp in (card.get("key_points") or [])[:3]:
        parts.append(f"- {kp}")
    parts.append(f"Tags: {', '.join(card.get('tags') or [])}")
    return "\n".join(parts)


# ============================================================
# 单 case 执行
# ============================================================
def run_case(case: Dict, strategy: str = "both") -> Dict:
    cid = case["id"]
    question = case.get("question", (case.get("turns") or [{}])[0].get("question", ""))
    knowledge_id = case.get("knowledge_id", "")
    session_id = case.get("session_id", f"eval_{cid}")
    context_text = build_context_text(knowledge_id)
    ctx_payload = {"knowledge_id": knowledge_id} if knowledge_id else None

    out = {"id": cid, "question": question, "knowledge_id": knowledge_id}

    if strategy in ("plain", "both"):
        plain = call_agent(question, session_id + "_plain", None)
        out["plain"] = {
            "answer": plain["answer"][:400],
            "tokens": plain["metadata"]["token_usage"].get("total_tokens", 0),
            "latency_ms": plain["metadata"]["latency_ms"],
            "scores": judge_answer(context_text, question, plain["answer"]),
        }
    if strategy in ("context", "both"):
        ctx = call_agent(question, session_id + "_ctx", ctx_payload)
        out["context"] = {
            "answer": ctx["answer"][:400],
            "tokens": ctx["metadata"]["token_usage"].get("total_tokens", 0),
            "latency_ms": ctx["metadata"]["latency_ms"],
            "scores": judge_answer(context_text, question, ctx["answer"]),
        }
        out["context_applied"] = ctx["metadata"].get("context_applied", False)
        # Router 决策（Phase 3.4b）: should_inject / score
        router = ctx["metadata"].get("router")
        if router:
            out["router_decision"] = router.get("should_inject")
            out["router_score"] = router.get("score")
            out["router_reason"] = router.get("reason")

    return out


# ============================================================
# 汇总（related cases）
# ============================================================
def summarize(results: List[Dict]) -> Dict[str, Any]:
    def avg(nums):
        return round(sum(nums) / len(nums), 2) if nums else 0

    summary = {"n_cases": len(results)}
    for key in ("plain", "context"):
        subset = [r[key] for r in results if key in r]
        if not subset:
            continue
        scores = [r["scores"] for r in subset]
        summary[key] = {
            "relevance": avg([s["relevance"] for s in scores]),
            "grounding": avg([s["grounding"] for s in scores]),
            "answerability": avg([s["answerability"] for s in scores]),
            "hallucination_rate": round(
                sum(1 for s in scores if s["hallucination"]) / len(scores) * 100, 1
            ),
            "avg_tokens": avg([r["tokens"] for r in subset]),
            "avg_latency_ms": avg([r["latency_ms"] for r in subset]),
        }
    return summary


# ============================================================
# Router 决策评估（Phase 3.4b）
# ============================================================
def router_accuracy(cases: List[Dict], results: List[Dict]) -> Dict[str, Any]:
    """should_inject vs router_decision（实际决策）

    指标:
      accuracy = (TP + TN) / total
      precision = TP / (TP + FP)
      recall = TP / (TP + FN)
      fp / fn 计数
    """
    tp = fp = tn = fn = 0
    failures = []
    details = []
    for case, res in zip(cases, results):
        should = case.get("should_inject", True)
        actual = res.get("router_decision", res.get("context_applied", False))
        # Router 决策缺失（如 3.4a 无 router metadata）时用 context_applied 兜底
        if actual is None:
            actual = res.get("context_applied", False)

        if should and actual:
            tp += 1
        elif should and not actual:
            fn += 1
            failures.append(_router_failure(case, res, "router_false_negative"))
        elif not should and actual:
            fp += 1
            failures.append(_router_failure(case, res, "router_false_positive"))
        else:
            tn += 1

        details.append(
            {
                "id": case["id"],
                "should_inject": should,
                "actual_inject": actual,
                "score": res.get("router_score"),
                "correct": should == actual,
            }
        )

    total = tp + fp + tn + fn
    return {
        "accuracy": round((tp + tn) / total * 100, 1) if total else 0,
        "precision": round(tp / (tp + fp) * 100, 1) if (tp + fp) else 0,
        "recall": round(tp / (tp + fn) * 100, 1) if (tp + fn) else 0,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "details": details,
        "failures": failures,
    }


def _router_failure(case: Dict, res: Dict, error_type: str) -> Dict[str, Any]:
    """构造 Router 失败记录（供未来 Supervisor Agent 使用）"""
    return {
        "case_id": case["id"],
        "query": case.get("question", ""),
        "knowledge_id": case.get("knowledge_id", ""),
        "context": res.get("context", {}).get("answer", "")[:200],
        "expected": case.get("should_inject", True),
        "actual": res.get("router_decision", res.get("context_applied", False)),
        "score": res.get("router_score"),
        "reason": res.get("router_reason", ""),
        "error_type": error_type,
    }


# ============================================================
# 稳定性测试
# ============================================================
def stability_check(case: Dict, runs: int = 3) -> Dict[str, Any]:
    """同 case 跑 N 次，统计 score variance"""
    scores = []
    for i in range(runs):
        r = run_case(case, strategy="context")
        scores.append(r["context"]["scores"])
    result = {}
    for dim in ("relevance", "grounding", "answerability"):
        vals = [s[dim] for s in scores]
        result[dim] = {
            "values": vals,
            "std": round(statistics.pstdev(vals), 2) if len(vals) > 1 else 0,
            "mean": round(sum(vals) / len(vals), 2),
        }
    return {"id": case["id"], "runs": runs, "dims": result}


# ============================================================
# 报告输出
# ============================================================
def print_table(summary: Dict[str, Any]) -> None:
    p, c = summary.get("plain", {}), summary.get("context", {})
    print("\n" + "=" * 52)
    print("Plain Agent           vs           Context Agent")
    print("=" * 52)
    if not p or not c:
        print("（单策略模式，无对比）")
        return
    print(f"{'Metric':<22}{'Plain':>10}{'Context':>12}")
    print("-" * 52)
    rows = [
        ("Relevance (1-5)", p["relevance"], c["relevance"]),
        ("Grounding (1-5)", p["grounding"], c["grounding"]),
        ("Answerability (1-5)", p["answerability"], c["answerability"]),
        ("Hallucination (%)", p["hallucination_rate"], c["hallucination_rate"]),
        ("Avg Tokens", p["avg_tokens"], c["avg_tokens"]),
        ("Avg Latency (ms)", p["avg_latency_ms"], c["avg_latency_ms"]),
    ]
    for name, pv, cv in rows:
        print(f"{name:<22}{pv:>10}{cv:>12}")
    print("=" * 52)


def save_report(dataset: str, payload: Dict[str, Any], tag: str = "") -> Path:
    ts = tag or "latest"
    out = RESULTS_DIR / f"{dataset}_{ts}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ============================================================
# main
# ============================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="Context-aware Agent Eval Runner")
    parser.add_argument("--dataset", default="generated", choices=list(DATASETS.keys()))
    parser.add_argument("--strategy", default="both", choices=["plain", "context", "both"])
    parser.add_argument("--case", default="", help="单个 case id")
    parser.add_argument("--limit", type=int, default=0, help="最多跑 N 个 case")
    parser.add_argument("--stability", type=int, default=0, help="稳定性测试: 对前 N 个 case 各跑 3 次")
    args = parser.parse_args()

    cases = load_cases(args.dataset)
    if not cases:
        print(f"[ERROR] dataset '{args.dataset}' 无 case（检查 {DATASETS[args.dataset]}）")
        sys.exit(1)
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if args.limit:
        cases = cases[: args.limit]

    print(f"dataset={args.dataset} | cases={len(cases)} | strategy={args.strategy}")

    results = []
    for case in cases:
        q = case.get("question", (case.get("turns") or [{}])[0].get("question", ""))
        print(f"\n=== {case['id']} [{case.get('case_type','')}] {q[:38]} ===")
        try:
            r = run_case(case, args.strategy)
            results.append(r)
            for key in ("plain", "context"):
                if key in r:
                    print(f"  {key}: tokens={r[key]['tokens']} scores={r[key]['scores']}")
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {str(exc)[:120]}")

    payload: Dict[str, Any] = {"dataset": args.dataset, "strategy": args.strategy, "n_cases": len(results)}

    # Related 质量评估
    summary = summarize(results)
    payload["summary"] = summary
    print_table(summary)

    # 保存 per-case 明细（供 failure analysis / breakdown 使用）
    payload["cases"] = results

    # Category breakdown + improvement rate（仅 related dataset 且 both 策略）
    if args.dataset != "router" and args.strategy == "both":
        from collections import defaultdict

        cat_map = defaultdict(lambda: {"n": 0, "improved": 0, "plain_rel": 0.0, "ctx_rel": 0.0})
        total_improved = 0
        for case, res in zip(cases, results):
            if "plain" not in res or "context" not in res:
                continue
            ctype = case.get("case_type", "unknown")
            entry = cat_map[ctype]
            p_rel = res["plain"]["scores"]["relevance"]
            c_rel = res["context"]["scores"]["relevance"]
            entry["n"] += 1
            entry["plain_rel"] += p_rel
            entry["ctx_rel"] += c_rel
            if c_rel > p_rel:
                entry["improved"] += 1
                total_improved += 1
        breakdown = {}
        for ctype, e in cat_map.items():
            breakdown[ctype] = {
                "n": e["n"],
                "improved": e["improved"],
                "improvement_rate": round(e["improved"] / e["n"] * 100, 1) if e["n"] else 0,
                "plain_avg_relevance": round(e["plain_rel"] / e["n"], 2) if e["n"] else 0,
                "ctx_avg_relevance": round(e["ctx_rel"] / e["n"], 2) if e["n"] else 0,
            }
        n_total = sum(e["n"] for e in cat_map.values())
        payload["category_breakdown"] = breakdown
        payload["overall_improvement_rate"] = round(total_improved / n_total * 100, 1) if n_total else 0
        print("\n=== Category Breakdown ===")
        for ctype, b in breakdown.items():
            print(
                f"  {ctype:<22} n={b['n']:>3} improved={b['improved']:>3} "
                f"({b['improvement_rate']:>5.1f}%) plain_rel={b['plain_avg_relevance']} ctx_rel={b['ctx_avg_relevance']}"
            )
        print(f"  整体提升率: {payload['overall_improvement_rate']}%")

    # Router 决策评估
    if args.dataset == "router":
        ra = router_accuracy(cases, results)
        payload["router"] = ra
        print(f"\nRouter Metrics:")
        print(f"  accuracy={ra['accuracy']}% precision={ra['precision']}% recall={ra['recall']}%")
        print(f"  TP={ra['tp']} TN={ra['tn']} FP={ra['fp']} FN={ra['fn']}")
        for d in ra["details"]:
            mark = "OK" if d["correct"] else "MISS"
            print(f"  [{mark}] {d['id'][:24]} should={d['should_inject']} actual={d['actual_inject']} score={d['score']}")
        # 保存 Router 失败记录（供 Supervisor Agent）
        if ra["failures"]:
            fail_out = ROOT / "eval" / "results" / "router_failures.json"
            fail_out.parent.mkdir(parents=True, exist_ok=True)
            fail_out.write_text(
                json.dumps({"failures": ra["failures"]}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            print(f"\nRouter 失败记录已写入: {fail_out} ({len(ra['failures'])} 条)")

    # 稳定性测试
    if args.stability:
        stables = [stability_check(c) for c in cases[: args.stability]]
        payload["stability"] = stables
        print(f"\n=== 稳定性测试（{args.stability} case × 3 runs）===")
        for s in stables:
            dims = ", ".join(f"{k}:std={v['std']}" for k, v in s["dims"].items())
            print(f"  {s['id'][:24]} {dims}")

    # 报告
    tag = f"stability{args.stability}" if args.stability else "latest"
    out = save_report(args.dataset, payload, tag)
    print(f"\n报告已写入: {out}")


if __name__ == "__main__":
    main()
