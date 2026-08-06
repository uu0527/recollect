"""
ReCollect Eval 测试数据 + 评分脚本（Phase 2）
三个评测维度：
  P2：广告识别准确率（ad 召回率、误杀率、review 率）
  P3：摘要质量（基于 P5 审计分作为 proxy + 要点覆盖率）
  P6：检索相关性（retrieved_note_ids 是否真的相关）
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parents[2]  # memory/eval/scoring.py → 项目根
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from schemas import (
    RawNote, ScreenedNote, SummarizedNote, AuditResult, RAGResult,
    load_jsonl, load_json,
)
from config import (
    path_raw, path_screened, path_summary, path_audit,
    EVAL_DIR,
)

# ============================================================
# 1) Gold 标注集（mini：10 条 demo 全部标注）
# ============================================================
GOLD_P2: Dict[str, Dict] = {
    # P1 的 note_id 用标题稳定匹配后映射
    # key = note_index (0..9)，脚本运行时转真实 note_id
    0: {"expected_decision": "drop",  "is_ad": True,  "note_type": "明显广告（面膜促销）"},
    1: {"expected_decision": "drop",  "is_ad": True,  "note_type": "带货软文（百搭神器+推广码）"},
    2: {"expected_decision": "review","is_ad": False, "note_type": "护肤问答（未明确广告）"},
    3: {"expected_decision": "review","is_ad": False, "note_type": "咖啡打卡（信息密度低）"},
    4: {"expected_decision": "review","is_ad": False, "note_type": "情绪倾诉（非知识）"},
    5: {"expected_decision": "keep",  "is_ad": False, "note_type": "副业干货（高价值）"},
    6: {"expected_decision": "keep",  "is_ad": False, "note_type": "落户流程（强结构化）"},
    7: {"expected_decision": "keep",  "is_ad": False, "note_type": "Pandas 教程（代码示例）"},
    8: {"expected_decision": "keep",  "is_ad": False, "note_type": "健身增肌计划（饮食+训练）"},
    9: {"expected_decision": "keep",  "is_ad": False, "note_type": "AI PM 求职面经（题库+写法）"},
}

GOLD_P6_QUERIES: List[Dict] = [
    {
        "query_id": "q1",
        "query": "程序员副业有哪些可以快速起步的方向？有哪些坑？",
        "relevant_note_indices": [5],  # 副业指南
        "nice_to_have_indices": [9],  # AI PM 求职也有一定相关
    },
    {
        "query_id": "q2",
        "query": "上海落户的完整流程和材料清单是什么？",
        "relevant_note_indices": [6],
        "nice_to_have_indices": [],
    },
    {
        "query_id": "q3",
        "query": "想做数据分析，常用的 Pandas 技巧？",
        "relevant_note_indices": [7],
        "nice_to_have_indices": [],
    },
]


# ============================================================
# 2) 辅助：把 note 标题映射到 gold index
# ============================================================
def _build_id_to_gold(task_id: str) -> Dict[str, Dict]:
    raws = load_jsonl(str(path_raw(task_id)), RawNote)
    # 按排序对齐（P1 的 10 条顺序就是 _DEMO_NOTES 原顺序）
    out: Dict[str, Dict] = {}
    for i, r in enumerate(raws):
        if i in GOLD_P2:
            out[r.note_id] = {"index": i, **GOLD_P2[i]}
    return out


# ============================================================
# 3) P2 评分
# ============================================================
def eval_p2(task_id: str) -> Dict:
    id2gold = _build_id_to_gold(task_id)
    screened = load_jsonl(str(path_screened(task_id)), ScreenedNote)
    total_ad = 0
    total_non_ad = 0
    ad_tp = 0  # 广告被正确识别（decision=drop 或 is_ad=True）
    ad_fn = 0  # 广告漏网（被 keep 或 review 但 gold=drop）
    mis_kill = 0  # 非广告被误 drop
    total_review = 0
    for s in screened:
        g = id2gold.get(s.note_id)
        if not g:
            continue
        if g["is_ad"]:
            total_ad += 1
            if s.decision == "drop":
                ad_tp += 1
            else:
                ad_fn += 1
        else:
            total_non_ad += 1
            if s.decision == "drop":
                mis_kill += 1
        if s.decision == "review":
            total_review += 1
    n = len(screened) or 1
    result = {
        "total": len(screened),
        "total_ad_gold": total_ad,
        "ad_recall": round(ad_tp / max(1, total_ad), 4),
        "miss_drop_rate_non_ad": round(mis_kill / max(1, total_non_ad), 4),
        "review_rate": round(total_review / n, 4),
        "decision_distribution": dict(Counter(s.decision for s in screened)),
    }
    return result


# ============================================================
# 4) P3 评分（基于 P5 审计分）
# ============================================================
def eval_p3(task_id: str) -> Dict:
    audits: List[AuditResult] = (
        load_jsonl(str(path_audit(task_id)), AuditResult) if path_audit(task_id).exists() else []
    )
    summaries = load_json(str(path_summary(task_id)), SummarizedNote)
    if not audits:
        return {"total_summary": len(summaries), "audit_samples": 0, "note": "无审计数据，跳过 P3 评分"}
    scores = [a.audit_score for a in audits]
    fid = [a.fidelity_score for a in audits]
    cov = [a.coverage_score for a in audits]
    cat = [a.category_score for a in audits]
    return {
        "total_summary": len(summaries),
        "audit_samples": len(audits),
        "audit_ratio": round(len(audits) / max(1, len(summaries)), 4),
        "avg_audit_score": round(sum(scores) / len(scores), 4),
        "avg_fidelity": round(sum(fid) / len(fid), 4),
        "avg_coverage": round(sum(cov) / len(cov), 4),
        "avg_category": round(sum(cat) / len(cat), 4),
        "pass_rate_ge_06": round(sum(1 for s in scores if s >= 0.6) / len(scores), 4),
        "pass_rate_ge_08": round(sum(1 for s in scores if s >= 0.8) / len(scores), 4),
    }


# ============================================================
# 5) P6 检索相关性评分
# ============================================================
def eval_p6(task_id: str) -> Dict:
    id2gold = _build_id_to_gold(task_id)
    index_to_noteid = {v["index"]: nid for nid, v in id2gold.items()}
    results = []
    for q in GOLD_P6_QUERIES:
        rag_path = BASE_DIR / "data" / "06_memory" / f"{task_id}_rag_{q['query_id']}.json"
        if not rag_path.exists():
            continue
        with open(rag_path, "r", encoding="utf-8") as f:
            d = json.load(f)
        retrieved: List[str] = d.get("retrieved_note_ids", [])
        gold_ids = {index_to_noteid[i] for i in q["relevant_note_indices"] if i in index_to_noteid}
        nice_ids = {index_to_noteid[i] for i in q.get("nice_to_have_indices", []) if i in index_to_noteid}
        hits = sum(1 for rid in retrieved if rid in gold_ids)
        nice = sum(1 for rid in retrieved if rid in nice_ids)
        precision = hits / max(1, len(retrieved))
        recall = hits / max(1, len(gold_ids)) if gold_ids else 0.0
        relevant_rate = (hits + nice * 0.5) / max(1, len(retrieved))
        results.append({
            "query_id": q["query_id"],
            "query": q["query"],
            "top_k": len(retrieved),
            "retrieved": retrieved,
            "gold_ids": sorted(gold_ids),
            "hits": hits,
            "nice": nice,
            "precision@k": round(precision, 4),
            "recall@k": round(recall, 4),
            "relevant_rate": round(relevant_rate, 4),
        })
    macro = {
        "queries_evaluated": len(results),
        "avg_precision_at_k": round(sum(r["precision@k"] for r in results) / max(1, len(results)), 4),
        "avg_recall_at_k":    round(sum(r["recall@k"] for r in results) / max(1, len(results)), 4),
        "avg_relevant_rate":  round(sum(r["relevant_rate"] for r in results) / max(1, len(results)), 4),
    }
    return {"per_query": results, "summary": macro}


# ============================================================
# 6) 反例/错误案例记录
# ============================================================
def collect_errors(task_id: str) -> List[Dict]:
    errors: List[Dict] = []
    id2gold = _build_id_to_gold(task_id)
    screened = load_jsonl(str(path_screened(task_id)), ScreenedNote)
    for s in screened:
        g = id2gold.get(s.note_id)
        if not g:
            continue
        if s.decision != g["expected_decision"]:
            errors.append({
                "type": "P2_decision_mismatch",
                "note_id": s.note_id,
                "gold": g["expected_decision"],
                "pred": s.decision,
                "reason": s.reason,
                "gold_type": g["note_type"],
            })
    return errors


# ============================================================
# 7) 运行全部 + 写报告
# ============================================================
def run_all_eval(task_id: str = "demo01", write: bool = True) -> Dict:
    rep = {
        "task_id": task_id,
        "p2": eval_p2(task_id),
        "p3": eval_p3(task_id),
        "p6": eval_p6(task_id),
        "errors": collect_errors(task_id),
    }
    if write:
        report_file = EVAL_DIR / f"report_{task_id}.json"
        errors_file = EVAL_DIR / f"error_cases_{task_id}.jsonl"
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        with open(errors_file, "w", encoding="utf-8") as f:
            for e in rep["errors"]:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        # Gold 数据也写一份
        gold_file = EVAL_DIR / f"gold_dataset_{task_id}.json"
        with open(gold_file, "w", encoding="utf-8") as f:
            json.dump({"GOLD_P2": GOLD_P2, "GOLD_P6_QUERIES": GOLD_P6_QUERIES}, f, ensure_ascii=False, indent=2)
        print(f"[Eval] 报告 -> {report_file}")
        print(f"[Eval] 错误 -> {errors_file}")
        print(f"[Eval] Gold -> {gold_file}")
    return rep


def pprint(task_id: str = "demo01") -> None:
    rep = run_all_eval(task_id, write=True)
    print("=" * 60)
    print(f"  ReCollect Eval Report  task_id={task_id}")
    print("=" * 60)
    print("[P2 筛选]")
    for k, v in rep["p2"].items():
        print(f"  - {k}: {v}")
    print("\n[P3 归纳（基于 P5 审计）]")
    for k, v in rep["p3"].items():
        print(f"  - {k}: {v}")
    print("\n[P6 检索问答]")
    for k, v in rep["p6"]["summary"].items():
        print(f"  - {k}: {v}")
    if rep["p6"]["per_query"]:
        for q in rep["p6"]["per_query"]:
            print(f"    • {q['query_id']} P={q['precision@k']} R={q['recall@k']} RR={q['relevant_rate']}  {q['query'][:30]}…")
    print(f"\n[反例库] {len(rep['errors'])} 条")
    for e in rep["errors"]:
        print(f"  - [{e['type']}] {e['note_id']}  gold={e['gold']} pred={e['pred']} ({e['gold_type']})  reason={e['reason']}")
    print("=" * 60)


if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else "demo01"
    pprint(tid)
