"""
P5 独立审计模块 - Mock 实现（Phase 2）
与 P3 生成逻辑完全隔离：按 audit_ratio 抽检；对每条进行 GSB 三维打分
- fidelity_score  保真度：归纳是否捏造原文不存在的信息
- coverage_score  覆盖度：是否遗漏原文主要要点（按 P3 key_points 数量 vs 原文编号点数量）
- category_score  分类正确：L1/L2 是否命中原文主题关键词
最终 audit_score = 0.4*fidelity + 0.35*coverage + 0.25*category
"""
from __future__ import annotations

import re
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from schemas import (
    RawNote, SummarizedNote, AuditResult,
    load_jsonl, load_json, dump_jsonl,
)
from config import path_raw, path_summary, path_audit
from pipeline._llm.factory import get_provider
from pipeline._llm.prompts import get_prompt


def _fidelity(note: RawNote, summary: SummarizedNote) -> float:
    """保真度：TLDR/要点/标签命中原文的比例；没命中扣到 0.5 以下"""
    text = (note.title + "\n" + note.content)
    claims: List[str] = []
    claims.append(summary.tldr)
    claims.extend(summary.key_points)
    # 拆关键词（中文按 2-gram 近似）：每个 claim 至少 60% 的关键词能在原文找到
    hits, total = 0, 0
    for c in claims:
        tokens = {c[i:i+2] for i in range(len(c)-1) if len(c[i:i+2].strip()) == 2}
        if not tokens:
            continue
        total += 1
        matched = sum(1 for t in tokens if t in text)
        if matched / max(1, len(tokens)) >= 0.55:
            hits += 1
    if total == 0:
        return 0.6
    base = hits / total
    # 摘要里有 "新增" 的数字/断言会丢分（模拟）
    hallucinate_flag = 0.0
    num_in_summary = re.findall(r"\d+", "".join(claims))
    num_in_raw = set(re.findall(r"\d+", text))
    extra_nums = [n for n in num_in_summary if n not in num_in_raw and len(n) >= 2]
    if extra_nums:
        hallucinate_flag = 0.1 * min(0.5, len(extra_nums) * 0.1)
    return round(max(0.3, min(1.0, base - hallucinate_flag)), 3)


def _coverage(note: RawNote, summary: SummarizedNote) -> float:
    """覆盖度：原文编号点的覆盖比例，或按句长分档"""
    raw_points = re.findall(r"\d+\.?[）\.]\s*[^\n。；]{10,}", note.content)
    if raw_points:
        # 原文有编号列表：看 kps 的 2-gram 在 raw_points 的命中
        kp_text = " ".join(summary.key_points)
        kp_bis = {kp_text[i:i+2] for i in range(len(kp_text)-1)}
        total_hit = 0
        for rp in raw_points:
            rp_bis = {rp[i:i+2] for i in range(len(rp)-1)}
            if kp_bis & rp_bis:
                total_hit += 1
        ratio = total_hit / max(1, len(raw_points))
        return round(min(1.0, ratio + 0.05), 3)
    # 没有编号：按原文长度给基础分（长文需要更多要点）
    clen = len(note.content)
    kp_cnt = len(summary.key_points)
    if clen > 500 and kp_cnt >= 4:
        return 0.85
    if clen > 300 and kp_cnt >= 3:
        return 0.75
    if clen > 150 and kp_cnt >= 2:
        return 0.65
    return 0.55


def _category(note: RawNote, summary: SummarizedNote) -> float:
    """L1/L2 关键词与原文重合度"""
    raw = note.title + "\n" + note.content
    targets = [summary.category_l1, summary.category_l2, *summary.tags[:3]]
    ok = sum(1 for t in targets if len(t) >= 2 and (t[:2] in raw or t[-2:] in raw))
    total = max(1, len(targets))
    return round(ok / total, 3)


def _comment(fid: float, cov: float, cat: float) -> str:
    pieces = []
    if fid >= 0.85:
        pieces.append("保真度高，无明显捏造")
    elif fid >= 0.7:
        pieces.append("保真度一般，存在少量措辞延展")
    else:
        pieces.append("保真度偏低，建议回查原文数字")
    if cov >= 0.85:
        pieces.append("覆盖充分")
    elif cov >= 0.65:
        pieces.append("覆盖尚可，有次要要点遗漏")
    else:
        pieces.append("覆盖偏低，建议重新提取要点")
    if cat >= 0.75:
        pieces.append("分类基本准确")
    else:
        pieces.append("分类可能偏，需人工复核")
    return "；".join(pieces)


def _normalize_p5(raw: Dict) -> Dict:
    """把 LLM 原始输出归一化到合法 AuditResult 字段（分数强制 0.0~1.0）"""
    def _clamp(v, lo=0.0, hi=1.0):
        try:
            return round(max(lo, min(hi, float(v))), 3)
        except (ValueError, TypeError):
            return round((lo + hi) / 2, 3)

    fid = _clamp(raw.get("fidelity_score", 0.5))
    cov = _clamp(raw.get("coverage_score", 0.5))
    cat = _clamp(raw.get("category_score", 0.5))
    # 重算 audit_score（不信任 LLM 自己算的加权）
    overall = round(0.40 * fid + 0.35 * cov + 0.25 * cat, 3)
    comments = str(raw.get("comments", "LLM 审计")).strip() or "LLM 审计"
    return {
        "audit_score": overall,
        "fidelity_score": fid,
        "coverage_score": cov,
        "category_score": cat,
        "comments": comments,
    }


# ============================================================
# 公共入口
# ============================================================
def run(task_id: str,
        audit_ratio: float | None = None,
        model_override: str | None = None,
        seed: int = 20260805,
        **kwargs) -> Path:
    """
    P5 审计：支持 mock 启发式 + 真实 LLM
    audit_ratio 默认 0.5（demo 提高覆盖率）；可在 MODEL_CONFIG.p5_audit 配置
    """
    ratio = 0.5 if audit_ratio is None else audit_ratio
    raw_map: Dict[str, RawNote] = {
        n.note_id: n for n in load_jsonl(str(path_raw(task_id)), RawNote)
    }
    summaries: List[SummarizedNote] = load_json(str(path_summary(task_id)), SummarizedNote)

    # 确定性抽样：按 note_id 排序 + 固定 seed 的 audit_ratio 比例前 N 条
    sorted_notes = sorted(summaries, key=lambda s: s.note_id)
    k = max(1, int(round(len(sorted_notes) * ratio))) if ratio < 1 else len(sorted_notes)
    rnd = random.Random(seed)
    sampled = rnd.sample(sorted_notes, k=min(k, len(sorted_notes)))

    # 选择 provider 和 prompt
    if model_override == "mock":
        # Mock 启发式：保留 Phase 2 行为
        use_heuristic = True
    else:
        # 尝试真实 LLM，若 factory 返回 mock 则自动回退启发式
        provider = get_provider("p5", force_new=True)
        use_heuristic = (provider.provider_name == "mock")
        if not use_heuristic:
            system_prompt, output_schema = get_prompt("p5")

    results: List[AuditResult] = []
    for s in sampled:
        note = raw_map.get(s.note_id)
        if note is None:
            continue

        if use_heuristic:
            # Phase 2 启发式逻辑
            fid = _fidelity(note, s)
            cov = _coverage(note, s)
            cat = _category(note, s)
            overall = round(0.40 * fid + 0.35 * cov + 0.25 * cat, 3)
            result = AuditResult(
                note_id=s.note_id,
                audit_score=overall,
                fidelity_score=fid,
                coverage_score=cov,
                category_score=cat,
                comments=_comment(fid, cov, cat),
                audit_time=datetime.now().isoformat(timespec="seconds"),
            )
        else:
            # Phase 3 真实 LLM 调用（不使用 schema 校验，用后处理归一化）
            user_content = f"原文标题：{note.title}\n原文内容：{note.content}\n归纳摘要：{s.tldr}\n要点：{' | '.join(s.key_points)}\n分类：{s.category_l1}/{s.category_l2}\n标签：{', '.join(s.tags)}"
            try:
                raw_result = provider.json_complete(system_prompt, user_content, schema=None)
                normalized = _normalize_p5(raw_result)
                result = AuditResult(
                    note_id=s.note_id,
                    **normalized,
                    audit_time=datetime.now().isoformat(timespec="seconds"),
                )
            except Exception as exc:
                # LLM 失败回退 mock
                print(f"[P5] LLM 调用失败，回退 mock: {exc!r}")
                fid = _fidelity(note, s)
                cov = _coverage(note, s)
                cat = _category(note, s)
                overall = round(0.40 * fid + 0.35 * cov + 0.25 * cat, 3)
                result = AuditResult(
                    note_id=s.note_id,
                    audit_score=overall,
                    fidelity_score=fid,
                    coverage_score=cov,
                    category_score=cat,
                    comments=_comment(fid, cov, cat),
                    audit_time=datetime.now().isoformat(timespec="seconds"),
                )

        results.append(result)

    out_path = path_audit(task_id)
    dump_jsonl(str(out_path), results, mode="w")
    avg = round(sum(r.audit_score for r in results) / max(1, len(results)), 3)
    extra = f"（模型覆盖={model_override}）" if model_override else ""
    print(f"[P5] task_id={task_id}  抽检 {len(results)}/{len(summaries)}  均审计分={avg} → {out_path.name}{extra}")
    return out_path
