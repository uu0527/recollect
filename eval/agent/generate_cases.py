"""
ReCollect Eval Case Generator (Phase 3.4a)

基于 Supabase 真实 knowledge 自动生成 Eval cases，不人工编写 query。

设计原则:
1. 每个 case 必须绑定真实 knowledge_id（来源 Supabase 已采集数据）
2. query 模拟真实用户意图，禁止改写 key_points 泄露答案
3. topic 只从 title / source_title 提取，禁止从 key_points 提取专有名词
4. 生成后 leakage check: query 含 key_points 独特实体 → rejected

输出:
  eval/agent/generated_cases.json   → Context Injection Quality cases（related）
  eval/agent/router_cases.json      → Context Router 决策 cases（irrelevant）

用法:
  python eval/agent/generate_cases.py            # 全部生成
  python eval/agent/generate_cases.py --limit 3  # 每条 knowledge 只生成 3 类（调试）
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_DIR = Path(__file__).resolve().parent
GENERATED_FILE = EVAL_DIR / "generated_cases.json"
ROUTER_FILE = EVAL_DIR / "router_cases.json"

# 中文停用词（topic 提取用，仅功能词，不拆地名）
STOPWORDS = set(
    "的 了 在 是 有 和 与 及 或 我 你 他 她 它 我们 你们 他们 这个 那个 什么 怎么 为什么 如何 吗 呢 啊 吧 就 都 也 很 更 最 不 没 要 会 能 可 以 让 从 到 对 于 并 且 还 而 之 其 中 关于 详细 具体 说说 了解 知道 请问 介绍 一下 篇 的 内容".split()
)

# ============================================================
# Topic 提取（只允许来自 title，禁止 key_points）
# ============================================================
def extract_topic(title: str) -> str:
    """从 title 提取主题实体（模拟用户口语主题词）。

    规则:
    - 优先取引号/书名号内的完整核心词（≤10 字）
    - 否则取第一个连续中文片段（完整保留，≤10 字；不截断语义）
    - title 超过 12 字时去掉口语前缀（求助/关于/想/原来/推荐 等）
    """
    if not title:
        return ""
    quoted = re.findall(r"[「」『』“”\"]([^「」『』“”\"]{2,})", title)
    if quoted:
        return quoted[0][:10]
    cleaned = re.sub(r"[｜|【】\[\]()（）《》:：,，.。!！?？]", " ", title)
    parts = [p.strip() for p in cleaned.split() if p.strip()]
    for p in parts:
        words = re.findall(r"[\u4e00-\u9fff]{3,}", p)
        if words:
            seg = words[0]
            # 仅当片段明显过长时去口语前缀（完整保留语义单元）
            if len(seg) > 10:
                for prefix in ("推荐", "求助贴", "求助", "关于", "如何", "为什么", "原来", "聪明人不要", "想你想", "哈圈"):
                    if seg.startswith(prefix):
                        seg = seg[len(prefix):]
                        break
            return seg[:10]
    cn = re.findall(r"[\u4e00-\u9fff]", title)
    return "".join(cn[:10]) if cn else title[:12]


# ============================================================
# 意图模板（模拟真实用户意图，弱化实体词）
#
# 设计原则:
# - query 不直接复述 title/实体词 → plain 模式 retriever 不会仅凭关键词命中
# - 用指代词（这篇/这个/这个话题）+ 意图 → 更接近真实用户"带着上下文提问"
# - 与 case 绑定的 knowledge_id 提供 judge 的"预期答案来源"
# ============================================================
TEMPLATES: Dict[str, List[str]] = {
    "summary": [
        "帮我总结一下这篇笔记的核心内容",
        "这篇笔记大概讲了什么？",
        "帮我看看这篇内容说了什么",
        "能简单概括下这个知识吗？",
    ],
    "source_grounding": [
        "这个知识具体有哪些关键信息？",
        "这篇内容有什么值得注意的细节？",
        "详细说说这篇的内容",
        "这个知识里有哪些具体的点？",
    ],
    "decision_support": [
        "这个信息对我做决定有帮助吗？",
        "基于这个知识，我该从哪入手？",
        "这个知识有什么参考价值？",
        "看完这个知识，接下来该怎么行动？",
        "这个内容能帮我做出更好的判断吗？",
    ],
    "knowledge_exploration": [
        "关于这个话题还有哪些细节？",
        "想多了解下这个知识",
        "这个话题具体是怎么说的？",
        "这个知识里还有什么我没注意到的？",
        "这个话题的背景是什么？",
    ],
}

# 无关问题池（Context Router 测试，与 knowledge 无关）
IRRELEVANT_QUERIES = [
    "如何优化 React 组件性能？",
    "Python 和 Go 怎么选？",
    "怎么做年度预算规划？",
    "推荐几个适合新手的前端框架",
    "如何写好一篇技术博客？",
    "Docker 和 K8s 的区别是什么？",
    "如何提升团队协作效率？",
    "什么是最优的数据库索引策略？",
    "如何设计一个 REST API？",
    "面试时如何回答优缺点问题？",
]


# ============================================================
# 泄露检测（query 是否包含 key_points 独特实体）
# ============================================================
def extract_key_entities(key_points: List[str]) -> List[str]:
    """从 key_points 提取独特实体词（长度 ≥2 的中文片段 + 数字/英文 token）"""
    entities = []
    for kp in key_points or []:
        # 中文 2-4 字片段
        cn_parts = re.findall(r"[\u4e00-\u9fff]{2,6}", kp)
        entities.extend(cn_parts)
        # 数字/英文 token（如 50台币、AIM、2027）
        tokens = re.findall(r"[0-9]+[a-zA-Z\u4e00-\u9fff]*|[A-Za-z]{2,}", kp)
        entities.extend(tokens)
    # 过滤过短的
    return [e for e in entities if len(e) >= 2]


def has_leak(query: str, key_entities: List[str], topic: str) -> bool:
    """判断 query 是否泄露 key_points 独有信息（排除 topic 本身）"""
    for ent in key_entities:
        if len(ent) < 2:
            continue
        # topic 或其一部分不算泄露（topic 本身来自 title 是允许的）
        if ent in topic or topic in ent:
            continue
        if ent in query:
            return True
    return False


# ============================================================
# 数据加载（Supabase knowledge）
# ============================================================
def load_knowledge() -> List[Dict]:
    from collector.context_store.adapters import get_adapter

    adapter = get_adapter()
    # 优先尝试 adapter 扩展的 list（若无，回退 Supabase 直查，只读）
    try:
        if hasattr(adapter, "list_knowledge"):
            return adapter.list_knowledge(limit=200)
    except Exception:
        pass
    # 回退：Supabase 只读查询（不修改数据）
    import os
    import config  # noqa: F401  # 加载 .env
    from supabase import create_client

    client = create_client(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", ""))
    resp = client.table("knowledge").select("*").limit(200).execute()
    rows = resp.data or []
    # 过滤测试数据（title 含"测试" 或 note_id 以 n_evt 开头）
    real = []
    for r in rows:
        title = r.get("title", "")
        if "测试" in title or "test" in title.lower():
            continue
        if str(r.get("note_id", "")).startswith("n_evt"):
            continue
        if not title.strip():
            continue
        real.append(r)
    return real


# ============================================================
# Leakage validation（title 关键词重合率 + key_points 专有名词）
# ============================================================
def title_keywords(title: str) -> List[str]:
    """从 title 提取连续中文字段（≥2 字），作为重合率检测基准"""
    if not title:
        return []
    return re.findall(r"[\u4e00-\u9fff]{2,}", title)


def title_overlap_ratio(query: str, title_keywords_list: List[str]) -> float:
    """query 与 title 关键词的重合率（0-1）。>0.5 判定泄露。"""
    if not title_keywords_list:
        return 0.0
    hits = sum(1 for kw in title_keywords_list if kw in query)
    return hits / len(title_keywords_list)


def validate_leakage(query: str, key_entities: List[str], title_kw: List[str]) -> str:
    """返回 'ok' 或泄露原因。"""
    # 1. title 关键词重合率（防完整 title / 连续关键短语）
    ratio = title_overlap_ratio(query, title_kw)
    if ratio > 0.5:
        return f"title_overlap:{ratio:.0%}"
    # 2. key_points 专有名词
    for ent in key_entities:
        if len(ent) >= 2 and ent in query:
            return f"kp_leak:{ent}"
    return "ok"


# ============================================================
# Case 生成
# ============================================================
def build_case(knowledge: Dict, case_type: str, query: str, template: str) -> Dict:
    return {
        "id": f"{knowledge['note_id'][:12]}_{case_type}_{abs(hash(query)) % 1000}",
        "knowledge_id": knowledge["note_id"],
        "question": query,
        "case_type": case_type,
        "mode": "context" if case_type != "irrelevant_context" else "irrelevant_context",
        "expected_topics": extract_key_entities(knowledge.get("key_points") or [])[:3],
        "source": "generated_from_real",
        "template": template,
        "quality_checked": False,
        "case_status": "pending",
    }


# 全局目标分布（10 条 knowledge → 60 cases）
#   summary <=20% (12) / source_grounding >=20% (12) / decision >=30% (18) / exploration >=30% (18)
TARGET_DIST = {
    "summary": 12,
    "source_grounding": 12,
    "decision_support": 18,
    "knowledge_exploration": 18,
}


def generate() -> Dict[str, Any]:
    knowledge_list = load_knowledge()
    related, router, rejected = [], [], []
    # 每类模板计数器（轮转取模板，保证 query 多样性）
    tpl_idx = {k: 0 for k in TEMPLATES}
    # 每类已生成数
    counts = {k: 0 for k in TEMPLATES}

    for kn in knowledge_list:
        note_id = kn["note_id"]
        title = kn.get("title", "")
        key_points = kn.get("key_points") or []
        key_entities = extract_key_entities(key_points)
        topic = extract_topic(title)
        title_kw = title_keywords(title)

        # 每条 knowledge 至少覆盖 1 种 case_type（coverage 保障）
        for case_type in TARGET_DIST:
            # 计算本条 knowledge 该生成多少个该类型 case：
            #   floor(target / n_knowledge) 基础 + 余数分配给前几个 knowledge
            per_knowledge = TARGET_DIST[case_type] // len(knowledge_list)
            remainder = TARGET_DIST[case_type] % len(knowledge_list)
            quota = per_knowledge + (1 if knowledge_list.index(kn) < remainder else 0)

            for _ in range(quota):
                templates = TEMPLATES[case_type]
                template = templates[tpl_idx[case_type] % len(templates)]
                tpl_idx[case_type] += 1
                query = template  # 意图模板已弱化实体词
                # 泄露检测（title 重合率 + key_points 专有名词）
                reason = validate_leakage(query, key_entities, title_kw)
                if reason != "ok":
                    rejected.append(
                        {"knowledge_id": note_id, "case_type": case_type, "query": query, "reason": reason}
                    )
                    continue
                case = build_case(kn, case_type, query, template)
                case["topic"] = topic  # 附加 topic 供分析（不注入 query）
                case["title_overlap_ratio"] = round(title_overlap_ratio(query, title_kw), 2)
                related.append(case)
                counts[case_type] += 1

        # 生成 1 个 irrelevant_context router case
        for i, q in enumerate(IRRELEVANT_QUERIES):
            if i % max(1, len(knowledge_list)) == knowledge_list.index(kn) % max(1, len(knowledge_list)):
                router.append(
                    {
                        "id": f"{note_id[:12]}_router_{abs(hash(q)) % 1000}",
                        "knowledge_id": note_id,
                        "query": q,
                        "case_type": "irrelevant_context",
                        "mode": "router",
                        "should_inject": False,
                        "source": "generated_from_real",
                        "quality_checked": False,
                        "case_status": "pending",
                    }
                )

    return {
        "related": related,
        "router": router,
        "rejected": rejected,
        "knowledge_count": len(knowledge_list),
        "counts": counts,
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="ReCollect Eval Case Generator")
    parser.add_argument("--limit", type=int, default=0, help="限制每条 knowledge 的 case 类型数（调试）")
    args = parser.parse_args()

    result = generate()
    related, router, rejected = result["related"], result["router"], result["rejected"]

    # 若 limit，只保留前 N 类
    if args.limit:
        types = sorted({c["case_type"] for c in related})[: args.limit]
        related = [c for c in related if c["case_type"] in types]

    GENERATED_FILE.write_text(
        json.dumps({"description": "Generated from real knowledge", "cases": related}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    ROUTER_FILE.write_text(
        json.dumps({"description": "Context Router decision cases", "cases": router}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    print(f"knowledge 总数: {result['knowledge_count']}")
    print(f"related cases: {len(related)}")
    print(f"router cases:  {len(router)}")
    print(f"rejected(leak): {len(rejected)}")
    # 分布
    print("case 分布:", {k: v for k, v in result.get("counts", {}).items()})
    # 泄露检测展示
    for r in rejected[:5]:
        print(f"  rejected: {r['query']} [{r['reason']}]")
    print(f"\n已写入: {GENERATED_FILE}")
    print(f"已写入: {ROUTER_FILE}")


if __name__ == "__main__":
    main()
