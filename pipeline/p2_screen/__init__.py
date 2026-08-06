"""
P2 AI 筛选模块 - Mock 实现（Phase 2）
基于关键词 + 元数据启发式规则模拟 LLM 三态决策输出
最终按 P2_THRESHOLDS 做路由：keep / review / drop
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from schemas import RawNote, ScreenedNote, load_jsonl, dump_jsonl
from config import path_raw, path_screened, P2_THRESHOLDS
from pipeline._llm.factory import get_provider
from pipeline._llm.prompts import get_prompt


# ============================================================
# 关键词词库（Mock LLM 启发式）
# ============================================================
AD_KEYWORDS = [
    "链接抢购", "私信我链接", "限时", "5折", "下单立减", "优惠券",
    "推广码", "专属优惠", "同款小样", "回购100次", "私信", "粉丝群",
    "评论区链接", "点击链接", "赶紧冲", "前100名", "备注", "立减",
    "必入", "闭眼入", "姐妹必入", "买出", "推广", "赞助",
]

VALUE_KEYWORDS = [
    "踩坑", "经验", "流程", "材料清单", "时间线", "避坑", "代码",
    "步骤", "计划", "模板", "面试题库", "简历", "全流程", "对比",
    "攻略", "教程", "技巧", "方法", "原则", "清单", "指南",
    "真实", "亲历", "干货", "总结", "高频",
]

EMOTION_KEYWORDS = ["心情", "压力", "哭了", "emo", "碎碎念", "希望明天"]
CHECKIN_KEYWORDS = ["打卡", "环境", "好拍", "排队", "中规中矩"]
ASK_KEYWORDS = ["蹲个", "有没有", "真实反馈", "姐妹们懂"]

CONTENT_TYPE_MAP = {
    "教程": ["教程", "技巧", "代码", "步骤", "方法", "10个", "模板"],
    "攻略": ["攻略", "指南", "流程", "时间线", "清单", "材料"],
    "测评": ["对比", "真实体验", "vs"],
    "资讯": ["2026", "最新", "求职", "简历", "面试"],
    "情绪": ["心情", "压力", "emo", "碎碎念", "哭了"],
}


def _keyword_score(text: str, keywords: List[str]) -> int:
    return sum(1 for k in keywords if k in text)


def _infer_content_type(title: str, content: str) -> str:
    text = title + "\n" + content
    best, best_ct = 0, "其他"
    for ct, kws in CONTENT_TYPE_MAP.items():
        s = _keyword_score(text, kws)
        if s > best:
            best, best_ct = s, ct
    return best_ct


def _heuristic_screen(note: RawNote) -> Tuple[float, int, str]:
    """返回 (ad_confidence, value_score, reason)"""
    text = note.title + "\n" + note.content
    ad_hit = _keyword_score(text, AD_KEYWORDS)
    value_hit = _keyword_score(text, VALUE_KEYWORDS)
    emotion_hit = _keyword_score(text, EMOTION_KEYWORDS)
    checkin_hit = _keyword_score(text, CHECKIN_KEYWORDS)
    ask_hit = _keyword_score(text, ASK_KEYWORDS)
    sponsored = 1 if note.metadata.get("is_sponsored") else 0

    # ad_confidence 0~1
    ad_conf = min(1.0, (ad_hit * 0.12 + sponsored * 0.65))
    if sponsored and ad_hit >= 2:
        ad_conf = max(ad_conf, 0.92)
    if ad_hit == 0 and not sponsored:
        ad_conf = min(ad_conf, 0.15)

    # value_score 1~5
    content_len = len(note.content)
    if value_hit >= 3 and content_len > 400:
        vs = 5
    elif value_hit >= 2 and content_len > 250:
        vs = 4
    elif value_hit >= 1 and content_len > 150:
        vs = 3
    elif emotion_hit or checkin_hit or ask_hit:
        vs = 2
    else:
        vs = 1

    # reason（一句话）
    reasons = []
    if ad_conf >= 0.85:
        reasons.append("广告特征明显（优惠券/链接/推广码/赞助标）")
    elif sponsored:
        reasons.append("标注为赞助内容")
    if value_hit >= 2:
        reasons.append(f"含{value_hit}个干货关键词，信息密度高")
    elif value_hit == 1:
        reasons.append("有少量干货关键词")
    if emotion_hit:
        reasons.append("情绪倾诉，无结构化信息")
    if checkin_hit:
        reasons.append("打卡类内容，信息密度低")
    if ask_hit:
        reasons.append("提问向，非知识输出")
    if not reasons:
        reasons.append("信息一般")
    reason = "；".join(reasons[:3])
    return ad_conf, vs, reason


def _route_decision(ad_conf: float, vs: int, th: Dict) -> Tuple[str, bool]:
    """三态路由 + is_ad"""
    is_ad = ad_conf >= th["ad_drop"]
    if ad_conf >= th["ad_drop"]:
        return "drop", is_ad
    if ad_conf < th["ad_review_low"] and vs >= th["value_keep_min"]:
        return "keep", is_ad
    return "review", is_ad


# ============================================================
# 公共入口
# ============================================================
def run(task_id: str, thresholds: Dict | None = None,
        model_override: str | None = None, **kwargs) -> Path:
    """
    P2 筛选：支持 mock 启发式 + 真实 LLM
    输入：01_raw/{task_id}_notes.jsonl
    输出：02_screened/{task_id}_screened.jsonl
    """
    th = {**P2_THRESHOLDS, **(thresholds or {})}
    raw_notes: List[RawNote] = load_jsonl(str(path_raw(task_id)), RawNote)
    results: List[ScreenedNote] = []

    # 选择 provider 和 prompt
    if model_override == "mock":
        # Mock 启发式：保留 Phase 2 行为
        provider_name = "mock"
        system_prompt, output_schema = "", {}
    else:
        # 真实 LLM：使用 factory + prompts
        provider = get_provider("p2")
        system_prompt, output_schema = get_prompt("p2")

    cnt = {"keep": 0, "review": 0, "drop": 0}
    for note in raw_notes:
        # 构造 user prompt
        user_content = f"笔记标题：{note.title}\n笔记内容：{note.content}\n元数据：{note.metadata}"

        if model_override == "mock":
            # Phase 2 启发式逻辑
            ad_conf, vs, reason = _heuristic_screen(note)
            decision, is_ad = _route_decision(ad_conf, vs, th)
            ct = _infer_content_type(note.title, note.content)
            result = ScreenedNote(
                note_id=note.note_id,
                decision=decision,
                ad_confidence=round(ad_conf, 3),
                is_ad=is_ad,
                content_type=ct,
                value_score=vs,
                reason=reason,
            )
        else:
            # Phase 3 真实 LLM 调用
            try:
                raw_result = provider.json_complete(system_prompt, user_content, schema=output_schema)
                # 填充 note_id 并映射到 ScreenedNote
                result = ScreenedNote(
                    note_id=note.note_id,
                    decision=raw_result.get("decision", "review"),
                    ad_confidence=raw_result.get("ad_confidence", 0.0),
                    is_ad=raw_result.get("is_ad", False),
                    content_type=raw_result.get("content_type", "其他"),
                    value_score=raw_result.get("value_score", 3),
                    reason=raw_result.get("reason", "无理由"),
                )
            except Exception as exc:
                # LLM 失败回退 mock
                print(f"[P2] LLM 调用失败，回退 mock: {exc!r}")
                ad_conf, vs, reason = _heuristic_screen(note)
                decision, is_ad = _route_decision(ad_conf, vs, th)
                ct = _infer_content_type(note.title, note.content)
                result = ScreenedNote(
                    note_id=note.note_id,
                    decision=decision,
                    ad_confidence=round(ad_conf, 3),
                    is_ad=is_ad,
                    content_type=ct,
                    value_score=vs,
                    reason=reason,
                )

        results.append(result)
        cnt[result.decision] += 1

    out_path = path_screened(task_id)
    dump_jsonl(str(out_path), results, mode="w")
    extra = f"（模型覆盖={model_override}）" if model_override else ""
    print(f"[P2] task_id={task_id}  keep={cnt['keep']} review={cnt['review']} drop={cnt['drop']} → {out_path.name}{extra}")
    return out_path
