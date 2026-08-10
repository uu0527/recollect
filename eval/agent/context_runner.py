"""
Context-aware Agent Eval Runner

验证 Knowledge Context Injection 是否提升 Agent 质量:
  Plain Agent vs Context Agent

用法:
  python eval/agent/context_runner.py                 # 全部 case
  python eval/agent/context_runner.py --case ctx_001  # 单个 case

输出: 控制台对比表 + eval/agent/context_results.json
数据记录: 复用 backend evaluator → eval/agent/agent_runs.jsonl（含 mode/context_applied）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "context_cases.json"
RESULTS_FILE = EVAL_DIR / "context_results.json"


def load_cases() -> List[Dict]:
    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    return data["cases"]


# ============================================================
# Agent 调用（复用 orchestrator，不改推理逻辑）
# ============================================================
def call_agent(question: str, session_id: str, context: Dict | None) -> Dict:
    from backend.agent.orchestrator import AgentOrchestrator

    orch = AgentOrchestrator()
    return orch.handle(query=question, session_id=session_id, context=context)


# ============================================================
# LLM-as-judge 评分
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
    "只输出 JSON: {{\"relevance\":1,\"grounding\":1,\"hallucination\":false}}\n"
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
            JUDGE_PROMPT, user, schema={"required": ["relevance", "grounding", "hallucination"]}
        )
        return {
            "relevance": int(raw.get("relevance", 1)),
            "grounding": int(raw.get("grounding", 1)),
            "hallucination": bool(raw.get("hallucination", True)),
        }
    except Exception as exc:
        print(f"  [judge] WARNING: 评分失败，用默认值: {type(exc).__name__}")
        return {"relevance": 1, "grounding": 1, "hallucination": True}


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
def run_case(case: Dict) -> Dict:
    cid = case["id"]
    question = case.get("question", (case.get("turns") or [{}])[0].get("question", ""))
    knowledge_id = case.get("knowledge_id", "")
    session_id = case.get("session_id", f"eval_{cid}")
    context_text = build_context_text(knowledge_id)

    # --- Plain（无 context）---
    plain = call_agent(question, session_id + "_plain", None)

    # --- Context（带 knowledge_id）---
    ctx_payload = {"knowledge_id": knowledge_id} if knowledge_id else None
    ctx = call_agent(question, session_id + "_ctx", ctx_payload)

    # --- Multi-turn 额外处理 ---
    turns = case.get("turns", [])
    turn_results = []
    if turns:
        for i, t in enumerate(turns):
            r = call_agent(t["question"], session_id + "_mt", ctx_payload)
            turn_results.append({"turn": i + 1, "answer_preview": r["answer"][:150]})

    # --- Judge 评分 ---
    plain_scores = judge_answer(context_text, question, plain["answer"])
    ctx_scores = judge_answer(context_text, question, ctx["answer"])

    return {
        "id": cid,
        "mode": case["mode"],
        "question": question,
        "knowledge_id": knowledge_id,
        "context_applied": ctx["metadata"].get("context_applied", False),
        "plain": {
            "answer": plain["answer"][:400],
            "tokens": plain["metadata"]["token_usage"].get("total_tokens", 0),
            "latency_ms": plain["metadata"]["latency_ms"],
            "scores": plain_scores,
        },
        "context": {
            "answer": ctx["answer"][:400],
            "tokens": ctx["metadata"]["token_usage"].get("total_tokens", 0),
            "latency_ms": ctx["metadata"]["latency_ms"],
            "scores": ctx_scores,
        },
        "multiturn": turn_results,
    }


# ============================================================
# 汇总
# ============================================================
def summarize(results: List[Dict]) -> Dict[str, Any]:
    def avg(nums):
        return round(sum(nums) / len(nums), 2) if nums else 0

    plain = [r["plain"] for r in results]
    ctx = [r["context"] for r in results]
    return {
        "n_cases": len(results),
        "plain": {
            "relevance": avg([r["scores"]["relevance"] for r in plain]),
            "grounding": avg([r["scores"]["grounding"] for r in plain]),
            "hallucination_rate": round(
                sum(1 for r in plain if r["scores"]["hallucination"]) / len(plain) * 100, 1
            ) if plain else 0,
            "avg_tokens": avg([r["tokens"] for r in plain]),
            "avg_latency_ms": avg([r["latency_ms"] for r in plain]),
        },
        "context": {
            "relevance": avg([r["scores"]["relevance"] for r in ctx]),
            "grounding": avg([r["scores"]["grounding"] for r in ctx]),
            "hallucination_rate": round(
                sum(1 for r in ctx if r["scores"]["hallucination"]) / len(ctx) * 100, 1
            ) if ctx else 0,
            "avg_tokens": avg([r["tokens"] for r in ctx]),
            "avg_latency_ms": avg([r["latency_ms"] for r in ctx]),
        },
    }


def print_table(summary: Dict[str, Any]) -> None:
    p, c = summary["plain"], summary["context"]
    rows = [
        ("Relevance (1-5)", p["relevance"], c["relevance"]),
        ("Grounding (1-5)", p["grounding"], c["grounding"]),
        ("Hallucination (%)", p["hallucination_rate"], c["hallucination_rate"]),
        ("Avg Tokens", p["avg_tokens"], c["avg_tokens"]),
        ("Avg Latency (ms)", p["avg_latency_ms"], c["avg_latency_ms"]),
    ]
    print("\n" + "=" * 46)
    print("Plain Agent           vs           Context Agent")
    print("=" * 46)
    print(f"{'Metric':<22}{'Plain':>10}{'Context':>12}")
    print("-" * 46)
    for name, pv, cv in rows:
        print(f"{name:<22}{pv:>10}{cv:>12}")
    print("=" * 46)


def main() -> None:
    parser = argparse.ArgumentParser(description="Context-aware Agent Eval Runner")
    parser.add_argument("--case", default="", help="单个 case id")
    args = parser.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]

    results = []
    for case in cases:
        q = case.get("question", (case.get("turns") or [{}])[0].get("question", ""))
        print(f"\n=== {case['id']} [{case['mode']}] {q[:40]} ===")
        try:
            r = run_case(case)
            results.append(r)
            print(f"  context_applied: {r['context_applied']}")
            print(f"  plain tokens={r['plain']['tokens']} ctx tokens={r['context']['tokens']}")
            print(f"  plain scores={r['plain']['scores']}")
            print(f"  ctx   scores={r['context']['scores']}")
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {str(exc)[:120]}")

    if results:
        summary = summarize(results)
        RESULTS_FILE.write_text(
            json.dumps({"summary": summary, "cases": results}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print_table(summary)
        print(f"\n结果已写入: {RESULTS_FILE}")


if __name__ == "__main__":
    main()
