"""
LLM Prompt Versioning（Phase 3）

每个阶段的 prompt 统一在此管理：
  get_prompt(stage, version="latest") → (system_prompt, output_schema)

版本命名约定：v1, v2, v3, ...  "latest" 始终指向最新稳定版本。
每次修改 prompt 必须新增版本，不允许原地修改已有版本（保证 eval 可复现）。

各阶段 output_schema 与 schemas.py 的 dataclass 字段一一对应：
  p2 → ScreenedNote（不含 note_id，由调用方填充）
  p3 → SummarizedNote（不含 note_id / url / content_type，由调用方填充）
  p5 → AuditResult（不含 note_id / audit_time，由调用方填充）
"""
from __future__ import annotations

from typing import Any, Dict, Tuple

# ----------------------------------------------------------------
# 类型别名
# ----------------------------------------------------------------
PromptPair = Tuple[str, Dict[str, Any]]  # (system_prompt, json_schema)


# ================================================================
# P2 筛选 prompt
# ================================================================
_P2_PROMPTS: Dict[str, PromptPair] = {
    "v1": (
        # system
        """\
你是一个内容质量筛选助手，专门识别小红书笔记中的广告和低质内容。
判断规则：
- 高广告特征：含"链接/优惠券/推广码/赞助/限时/私信我"等词，或由品牌商赞助。
- 高价值内容：含实用干货、步骤、攻略、真实经验、数据对比等。
- 灰区：无法确定时归入 review。
输出严格的 JSON，不输出任何额外文字。""",
        # output schema
        {
            "type": "object",
            "required": ["is_ad", "ad_confidence", "content_type", "value_score", "decision", "reason"],
            "properties": {
                "is_ad":          {"type": "boolean"},
                "ad_confidence":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "content_type":   {"type": "string", "enum": ["攻略", "测评", "教程", "资讯", "情绪", "其他"]},
                "value_score":    {"type": "integer", "minimum": 1, "maximum": 5},
                "decision":       {"type": "string", "enum": ["keep", "review", "drop"]},
                "reason":         {"type": "string"},
            },
        },
    ),
    "v2": (
        # system
        """\
你是小红书收藏夹内容筛选器。对每个笔记必须给出三态决策：keep / review / drop。

【决策定义】
- keep：高价值知识内容，值得直接入库。标准：有结构化信息、可复用经验、步骤/清单/数据/代码/真实案例。
- drop：广告/软广/带货/低质内容。标准：含"私信我""链接""优惠券""推广码""限时""必入""闭眼入""备注"等营销词，或明确标注赞助/广告。
- review：灰区。标准：信息密度低、纯情绪、打卡、提问、个人碎碎念，或价值与广告特征都不明显。

【判定顺序】
1. 先看是否广告/软广：是 → drop（ad_confidence≥0.85）。
2. 再看是否高价值干货：是 → keep（ad_confidence<0.3 且 value_score≥4）。
3. 其余 → review。

【字段说明】
- is_ad: 是否为广告（ad_confidence≥0.7）。
- ad_confidence: 0.0~1.0，广告置信度。
- content_type: "攻略""测评""教程""资讯""情绪""其他"。
- value_score: 1~5，信息价值评分（5=极高价值，1=无价值）。
- decision: "keep"/"review"/"drop"，必须三选一，不能含糊。
- reason: 一句话解释决策依据。

【示例】
标题：2026程序员副业指南：从0到月入过万（踩坑经验+全步骤）
内容：...详细步骤、踩坑经验、真实案例...
输出：{"is_ad": false, "ad_confidence": 0.1, "content_type": "攻略", "value_score": 5, "decision": "keep", "reason": "高价值副业攻略，含步骤、踩坑与真实案例"}

标题：月薪3k买出3w效果这件百搭神器闭眼入 私信我链接
内容：限时5折，点击链接抢购，备注暗号再减20
输出：{"is_ad": true, "ad_confidence": 0.95, "content_type": "其他", "value_score": 1, "decision": "drop", "reason": "带货软广，含私信链接与限时营销词"}

标题：今天去XX咖啡打卡了 环境还不错
内容：周末人好多，拍了几张照，咖啡一般
输出：{"is_ad": false, "ad_confidence": 0.05, "content_type": "情绪", "value_score": 2, "decision": "review", "reason": "打卡类低信息密度内容"}

严格输出 JSON，不输出任何额外文字。""",
        # output schema（与 v1 相同）
        {
            "type": "object",
            "required": ["is_ad", "ad_confidence", "content_type", "value_score", "decision", "reason"],
            "properties": {
                "is_ad":          {"type": "boolean"},
                "ad_confidence":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "content_type":   {"type": "string", "enum": ["攻略", "测评", "教程", "资讯", "情绪", "其他"]},
                "value_score":    {"type": "integer", "minimum": 1, "maximum": 5},
                "decision":       {"type": "string", "enum": ["keep", "review", "drop"]},
                "reason":         {"type": "string"},
            },
        },
    ),
}

# ================================================================
# P3 归纳 prompt
# ================================================================
_P3_PROMPTS: Dict[str, PromptPair] = {
    "v1": (
        # system
        """\
你是一个知识归纳助手，将小红书笔记提炼为结构化知识卡片。
要求：
- tldr：一句话总结，≤60字。
- key_points：3-5条核心要点，每条≤80字，只保留有信息量的内容。
- category_l1：从[职场发展,技能学习,生活方式,运动健身,美妆护肤,职业求职,城市资讯,知识管理]中选一。
- category_l2：对应细分方向（如"数据分析""落户指南"），若无合适则填"综合"。
- tags：3-6个关键词标签。
- actionable：可执行建议或适用场景，≤100字。
- quality_flags：若内容有缺陷请填写（如"信息稀少""无可执行建议"），否则留空数组。
严格输出 JSON，不输出额外文字。""",
        # output schema
        {
            "type": "object",
            "required": ["category_l1", "category_l2", "tags", "tldr", "key_points", "actionable", "quality_flags"],
            "properties": {
                "category_l1":   {"type": "string"},
                "category_l2":   {"type": "string"},
                "tags":          {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "tldr":          {"type": "string"},
                "key_points":    {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "actionable":    {"type": "string"},
                "quality_flags": {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
}

# ================================================================
# P5 审计 prompt
# ================================================================
_P5_PROMPTS: Dict[str, PromptPair] = {
    "v1": (
        # system
        """\
你是一个独立内容审计员，负责审查 AI 归纳摘要的质量。
你只能看到原始笔记和摘要，不能依赖生成摘要的 AI 的判断。
三维评分（0.0-1.0）：
- fidelity_score（保真度）：摘要内容是否忠实于原文，有无捏造信息。
- coverage_score（覆盖度）：原文主要要点是否都被摘要涵盖。
- category_score（分类准确）：L1/L2 分类和标签是否与原文主题吻合。
计算 audit_score = 0.4×fidelity + 0.35×coverage + 0.25×category（保留3位小数）。
comments：一句话综合点评，指出主要问题（如无问题填"归纳质量良好"）。
严格输出 JSON，不输出额外文字。""",
        # output schema
        {
            "type": "object",
            "required": ["fidelity_score", "coverage_score", "category_score", "audit_score", "comments"],
            "properties": {
                "fidelity_score":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "coverage_score":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "category_score":  {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "audit_score":     {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "comments":        {"type": "string"},
            },
        },
    ),
}

# ================================================================
# P6 RAG 回答 prompt
# ================================================================
_P6_PROMPTS: Dict[str, PromptPair] = {
    "v1": (
        # system
        """\
你是一个知识库问答助手，只能基于提供的检索片段回答问题。
规则：
- 回答必须有据可查，只能使用检索片段中的信息。
- 若检索片段与问题无关，如实说明"知识库中暂时没有相关内容"。
- answer：直接回答问题，≤200字，不要重复原文。
- confidence：high（检索内容高度相关）/ medium（部分相关）/ low（相关性弱）。
严格输出 JSON，不输出额外文字。""",
        # output schema
        {
            "type": "object",
            "required": ["answer", "confidence"],
            "properties": {
                "answer":     {"type": "string"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            },
        },
    ),
}

# ================================================================
# 注册表 + latest 指针
# ================================================================
_REGISTRY: Dict[str, Dict[str, PromptPair]] = {
    "p2": _P2_PROMPTS,
    "p3": _P3_PROMPTS,
    "p5": _P5_PROMPTS,
    "p6": _P6_PROMPTS,
}

_LATEST: Dict[str, str] = {
    "p2": "v2",
    "p3": "v1",
    "p5": "v1",
    "p6": "v1",
}


# ================================================================
# 公共接口
# ================================================================

def get_prompt(stage: str, version: str = "latest") -> PromptPair:
    """
    返回 (system_prompt, output_schema)。
    version="latest" 自动解析为各阶段最新稳定版本。

    用法示例：
        system, schema = get_prompt("p2")
        result = provider.json_complete(system, user_content, schema=schema)
    """
    if stage not in _REGISTRY:
        raise KeyError(f"未注册的 stage: {stage!r}，可选: {list(_REGISTRY)}")
    if version == "latest":
        version = _LATEST[stage]
    stage_versions = _REGISTRY[stage]
    if version not in stage_versions:
        raise KeyError(f"stage={stage!r} 中不存在 version={version!r}，可选: {list(stage_versions)}")
    return stage_versions[version]


def list_versions(stage: str) -> Dict[str, str]:
    """
    列出某阶段所有 prompt 版本及其 latest 指向。
    返回 {"latest": "v1", "versions": ["v1"]} 格式。
    """
    if stage not in _REGISTRY:
        raise KeyError(f"未注册的 stage: {stage!r}")
    return {
        "latest": _LATEST[stage],
        "versions": sorted(_REGISTRY[stage].keys()),
    }
