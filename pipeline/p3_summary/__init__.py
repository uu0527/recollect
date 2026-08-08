"""
P3 AI 归纳模块 - Mock 实现（Phase 2）
基于 P2 screened 的决策，仅处理 keep/review；输出严格 JSON 数组（SummarizedNote）
Mock LLM 归纳：启发式生成 TL;DR / 要点 / 分类 / 标签，保证 JSON Schema 100% 通过
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from schemas import (
    RawNote, ScreenedNote, SummarizedNote,
    load_jsonl, dump_json,
)
from config import path_raw, path_screened, path_summary
from pipeline._llm.router import get_stage_provider
from pipeline._llm.prompts import get_prompt


# ============================================================
# 分类体系（Mock 归纳）
# ============================================================
L1_CATEGORIES = [
    "职场发展", "技能学习", "生活方式", "运动健身",
    "美妆护肤", "职业求职", "城市资讯", "知识管理",
]


def _select_note_images(images: List[str]) -> List[str]:
    """Image Router：Vision 前筛选图片（降 token 成本，保高价值图）

    用下载 HEAD/部分字节获取尺寸与大小做评分；下载失败时
    降级为无 metadata 选择（仅 URL 去重 + 顺序）。
    不修改 RawNote 原始 images。
    """
    from collector.image_router import select_images

    if not images:
        return []

    def _metadata(url: str) -> Dict:
        """轻量获取图片 metadata（webp 头解析尺寸 + Content-Length），失败返回空"""
        try:
            import struct
            import urllib.request

            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                head = resp.read(40)  # webp 头足够解析宽高
                size_hint = resp.headers.get("Content-Length")
            meta: Dict = {}
            if size_hint:
                meta["size_bytes"] = int(size_hint)
            # WebP 尺寸：RIFF....WEBP + VP8X/VP8L/VP8 头
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                chunk = head[12:16]
                if chunk == b"VP8X" and len(head) >= 30:
                    w = struct.unpack("<I", head[24:27] + b"\x00")[0]
                    h = struct.unpack("<I", head[27:30] + b"\x00")[0]
                    meta["width"], meta["height"] = w, h
                elif chunk == b"VP8 " and len(head) >= 22:  # lossy
                    w = struct.unpack("<H", head[18:20])[0]
                    h = struct.unpack("<H", head[20:22])[0]
                    meta["width"], meta["height"] = w, h
                elif chunk == b"VP8L" and len(head) >= 25:  # lossless
                    bits = struct.unpack("<I", head[21:25])[0]
                    meta["width"] = (bits & 0x3FFF) + 1
                    meta["height"] = ((bits >> 14) & 0x3FFF) + 1
            return meta
        except Exception:
            return {}

    return select_images(images, metadata_provider=_metadata)


def _normalize_p3(raw: Dict) -> Dict:
    """把 LLM 原始输出归一化到合法 SummarizedNote 字段"""
    l1 = str(raw.get("category_l1", "")).strip()
    if l1 not in L1_CATEGORIES:
        l1 = "知识管理"

    l2 = str(raw.get("category_l2", "综合")).strip() or "综合"

    tags = raw.get("tags", [])
    if not isinstance(tags, list):
        tags = [str(tags)] if tags else ["其他"]
    tags = [str(t).strip() for t in tags if str(t).strip()][:6]
    if not tags:
        tags = ["其他"]

    tldr = str(raw.get("tldr", "")).strip() or "无摘要"
    if len(tldr) > 80:
        tldr = tldr[:80] + "…"

    kps = raw.get("key_points", [])
    if not isinstance(kps, list):
        kps = [str(kps)] if kps else ["无要点"]
    kps = [str(k).strip() for k in kps if str(k).strip()]
    if not kps:
        kps = ["无要点"]

    actionable = str(raw.get("actionable", "")).strip() or "无建议"
    qflags = raw.get("quality_flags", [])
    if not isinstance(qflags, list):
        qflags = []
    qflags = [str(f).strip() for f in qflags if str(f).strip()]

    return {
        "category_l1": l1,
        "category_l2": l2,
        "tags": tags,
        "tldr": tldr,
        "key_points": kps,
        "actionable": actionable,
        "content_type": "图文",
        "quality_flags": qflags,
    }

L1_L2_RULES: Dict[str, List[re.Pattern]] = {
    "职业求职": [re.compile(r"简历|面试|求职|offer|AI PM|PM"), re.compile(r"题库|面经")],
    "技能学习": [re.compile(r"Python|pandas|数据分析|代码|教程|技巧|编程")],
    "职场发展": [re.compile(r"副业|接包|咨询|课程|技能变现")],
    "城市资讯": [re.compile(r"上海|落户|户口|材料清单|时间线")],
    "运动健身": [re.compile(r"健身|增肌|训练|卧推|深蹲|饮食计划")],
    "美妆护肤": [re.compile(r"面膜|面霜|皮肤|闭口|护肤|熬夜|闺蜜")],
    "生活方式": [re.compile(r"打卡|咖啡|闺蜜|排队|周末|拍照|环境"), re.compile(r"心情|emo|碎碎念|压力")],
}

TAG_RULES = [
    (re.compile(r"副业|接包|变现"), ["副业", "赚钱", "踩坑"]),
    (re.compile(r"上海|落户|户口"), ["上海落户", "办事指南", "材料清单"]),
    (re.compile(r"Python|pandas|数据分析|代码"), ["Python", "Pandas", "数据分析"]),
    (re.compile(r"健身|增肌|训练|卧推"), ["健身", "增肌", "新手"]),
    (re.compile(r"简历|面试|求职|AI PM|PM"), ["求职", "简历", "AI产品经理"]),
    (re.compile(r"咖啡|打卡"), ["探店", "周末"]),
    (re.compile(r"面膜|面霜|熬夜|护肤"), ["护肤", "熬夜"]),
    (re.compile(r"emo|心情|碎碎念"), ["生活", "树洞"]),
]


def _classify(title: str, content: str) -> tuple[str, str]:
    text = title + "\n" + content
    matched_l1, matched_l2_pattern = "知识管理", None
    for l1, pats in L1_L2_RULES.items():
        for p in pats:
            if p.search(text):
                matched_l1 = l1
                matched_l2_pattern = p
                break
        else:
            continue
        break
    # L2：用匹配到的关键词拼
    l2_map = {
        "副业": "副业变现",
        "面试": "面试求职",
        "简历": "简历写作",
        "Python": "数据分析",
        "pandas": "数据分析",
        "健身": "健身训练",
        "落户": "城市指南",
        "咖啡": "探店打卡",
        "护肤": "护肤心得",
    }
    l2 = "综合"
    if matched_l2_pattern:
        for kw, label in l2_map.items():
            if kw in matched_l2_pattern.pattern:
                l2 = label
                break
    return matched_l1, l2


def _pick_tags(title: str, content: str) -> List[str]:
    text = title + "\n" + content
    tags: List[str] = []
    for pat, tgs in TAG_RULES:
        if pat.search(text):
            tags.extend(tgs)
    if not tags:
        tags = ["其他"]
    return list(dict.fromkeys(tags))[:6]


def _extract_key_points(content: str, n: int = 5) -> List[str]:
    """从编号列表中抽取要点；失败则按句拆分取前 N"""
    numbered = re.findall(r"\d+\.?[）\.]\s*([^\n。；]{10,120})", content)
    if numbered:
        cleaned = [re.sub(r"\s+", " ", p).strip() for p in numbered]
        result: List[str] = []
        seen = set()
        for c in cleaned:
            if c[:10] not in seen:
                seen.add(c[:10])
                result.append(c)
            if len(result) >= n:
                break
        return result
    sents = [s.strip() for s in re.split(r"[。；\n]", content) if 15 <= len(s.strip()) <= 120]
    return sents[:n]


def _make_tldr(title: str, kps: List[str], l1: str) -> str:
    if kps:
        lead = kps[0]
        if len(lead) > 60:
            lead = lead[:60] + "…"
        return f"关于「{l1}」的{title[:20]}：{lead}"
    return f"{title[:30]}：{l1}方向的一篇分享。"


def _make_actionable(title: str, content: str, l1: str, tags: List[str]) -> str:
    text = title + "\n" + content
    if "步骤" in text or "流程" in text or "材料" in text:
        return "适用场景：有明确办理目标时，可按文中时间线逐条准备并留 10% 缓冲时间，提前核实关键材料。"
    if "代码" in text or "技巧" in text or "教程" in text:
        return "适用场景：日常工作/学习直接按文中 10 条技巧逐条对照练习，每条至少跑 3 个真实案例。"
    if "健身" in text or "训练" in text:
        return "适用场景：新手增肌/塑型阶段，先确认动作标准再加重量，推拉腿每周 3 次配合热量盈余饮食。"
    if "副业" in text or "变现" in text:
        return "适用场景：主业稳定后想额外增收的人，先用 3 单成本价换案例 + 好评，再逐步提价。"
    if "简历" in text or "面试" in text:
        return "适用场景：求职季前 2-3 个月，逐条对照题库准备真实案例（STAR 写法），简历每个点准备 2-3 个故事。"
    if "打卡" in text or "咖啡" in text:
        return "适用场景：周末闲逛/拍照，作为备选地点，排队超过 15 分钟直接换店。"
    return f"适用场景：对「{l1}」相关主题感兴趣时，按需查阅要点。"


# ============================================================
# 公共入口
# ============================================================
def run(task_id: str,
        only_decisions: List[str] | None = None,
        skip_multimodal: bool = False,
        model_override: str | None = None,
        **kwargs) -> Path:
    """
    P3 归纳：支持 mock 启发式 + 真实 LLM
    默认 only_decisions = ["keep", "review"]（跳过 drop）
    skip_multimodal：Phase 2 已是纯文本，占位兼容
    """
    decisions = set(only_decisions or ["keep", "review"])
    raw_map: Dict[str, RawNote] = {
        n.note_id: n for n in load_jsonl(str(path_raw(task_id)), RawNote)
    }
    screened: List[ScreenedNote] = load_jsonl(str(path_screened(task_id)), ScreenedNote)

    # 选择 provider 和 prompt（Phase 3.5: 走 Model Router，按内容复杂度选模型）
    if model_override == "mock":
        # Mock 启发式：保留 Phase 2 行为
        use_heuristic = True
    else:
        # 尝试真实 LLM（智能路由：简单内容→智谱，复杂/技术→DeepSeek）
        provider = get_stage_provider("p3", task_id=task_id,
                                      task_type="summary", text="")
        use_heuristic = (provider.provider_name == "mock")
        if not use_heuristic:
            system_prompt, output_schema = get_prompt("p3")

    out: List[SummarizedNote] = []
    for s in screened:
        if s.decision not in decisions:
            continue
        note = raw_map.get(s.note_id)
        if note is None:
            continue

        if not use_heuristic:
            # 每条 note 独立路由：有图片 → 自动切 qwen3-vl-plus（Vision）；
            # 纯文本 → 按内容复杂度决定 DeepSeek/智谱
            # Image Router：Vision 前筛选图片（降 token 成本，保高价值图）
            selected_images = _select_note_images(note.images)
            provider = get_stage_provider("p3", task_id=task_id,
                                          task_type="summary",
                                          text=note.title + "\n" + note.content,
                                          images=selected_images or None)
            use_heuristic = (provider.provider_name == "mock")

        if use_heuristic:
            # Phase 2 启发式逻辑
            l1, l2 = _classify(note.title, note.content)
            tags = _pick_tags(note.title, note.content)
            kps = _extract_key_points(note.content)
            tldr = _make_tldr(note.title, kps, l1)
            actionable = _make_actionable(note.title, note.content, l1, tags)
            qflags: List[str] = []
            if skip_multimodal and note.images:
                qflags.append("skip_multimodal")
            if len(kps) < 3:
                qflags.append("low_points_count")
            ctype = "图文" if note.images else "视频" if any(t in tags for t in ["视频"]) else "图文"
            result = SummarizedNote(
                note_id=note.note_id,
                title=note.title,
                url=note.url,
                category_l1=l1,
                category_l2=l2,
                tags=tags,
                tldr=tldr,
                key_points=kps,
                actionable=actionable,
                content_type=ctype,
                quality_flags=qflags,
            )
        else:
            # Phase 3 真实 LLM 调用（不使用 schema 校验，用后处理归一化）
            user_content = f"笔记标题：{note.title}\n笔记内容：{note.content}\n元数据：{note.metadata}" + \
                           f"\n筛选决策：{s.decision}，置信度：{s.ad_confidence}，理由：{s.reason}"
            try:
                raw_result = provider.json_complete(system_prompt, user_content, schema=None)
                normalized = _normalize_p3(raw_result)
                result = SummarizedNote(
                    note_id=note.note_id,
                    title=note.title,
                    url=note.url,
                    **normalized,
                )
            except Exception as exc:
                # LLM 失败回退 mock
                print(f"[P3] LLM 调用失败，回退 mock: {exc!r}")
                l1, l2 = _classify(note.title, note.content)
                tags = _pick_tags(note.title, note.content)
                kps = _extract_key_points(note.content)
                tldr = _make_tldr(note.title, kps, l1)
                actionable = _make_actionable(note.title, note.content, l1, tags)
                qflags: List[str] = []
                if skip_multimodal and note.images:
                    qflags.append("skip_multimodal")
                if len(kps) < 3:
                    qflags.append("low_points_count")
                ctype = "图文" if note.images else "视频" if any(t in tags for t in ["视频"]) else "图文"
                result = SummarizedNote(
                    note_id=note.note_id,
                    title=note.title,
                    url=note.url,
                    category_l1=l1,
                    category_l2=l2,
                    tags=tags,
                    tldr=tldr,
                    key_points=kps,
                    actionable=actionable,
                    content_type=ctype,
                    quality_flags=qflags,
                )

        out.append(result)

    out_path = path_summary(task_id)
    dump_json(str(out_path), out)
    extra = f"（skip_multimodal={skip_multimodal}）" if skip_multimodal else ""
    extra += f"（模型覆盖={model_override}）" if model_override else ""
    print(f"[P3] task_id={task_id}  归纳 {len(out)} 条 → {out_path.name}{extra}")
    return out_path
