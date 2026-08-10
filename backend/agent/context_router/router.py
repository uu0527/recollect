"""
Context Router - V1 MVP

职责：根据 query 与 retrieved Knowledge Context 的相关性，决定是否注入。

策略（V1）: Lexical Similarity
  - 中文字符 bigram/trigram + 英文词 token
  - 计算 query 与 context 文本（title/tldr/tags/key_points）的重叠分
  - 可解释、零依赖、低成本（无需 LLM Judge）

输出 RouterDecision:
  {should_inject: bool, score: float, reason: str}

接口预留: 未来可换 Embedding Similarity（实现 _embed + _similarity 即可）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.agent.context_router.config import RouterConfig


@dataclass
class RouterDecision:
    should_inject: bool
    score: float
    reason: str
    # 附加诊断（供 eval / failure recording）
    query: str = ""
    context_text: str = ""
    strategy: str = "lexical"
    details: Dict[str, Any] = field(default_factory=dict)


class ContextRouter:
    """Knowledge Context 注入决策器"""

    def __init__(self, threshold: Optional[float] = None, strategy: Optional[str] = None) -> None:
        self.threshold = threshold if threshold is not None else RouterConfig.THRESHOLD
        self.strategy = strategy or RouterConfig.STRATEGY

    # ============================================================
    # 主入口
    # ============================================================
    def should_inject(self, query: str, context: Dict[str, Any]) -> RouterDecision:
        """根据 query 与 context 相关性决定是否注入。

        context: Knowledge Asset 字典（title/tldr/key_points/tags）
        """
        q = (query or "").strip()
        if not q:
            return RouterDecision(False, 0.0, "empty_query", query=q)

        context_text = self._context_text(context)
        if not context_text:
            return RouterDecision(False, 0.0, "empty_context", query=q)

        if self.strategy == "lexical":
            score, details = self._lexical_score(q, context_text)
        else:
            # fallback: 默认 lexical
            score, details = self._lexical_score(q, context_text)

        decision = score >= self.threshold
        reason = self._reason(decision, score)
        return RouterDecision(
            should_inject=decision,
            score=round(score, 4),
            reason=reason,
            query=q,
            context_text=context_text[:200],
            strategy=self.strategy,
            details=details,
        )

    # ============================================================
    # Lexical Similarity（V1）
    # ============================================================
    def _context_text(self, context: Dict[str, Any]) -> str:
        """把 Knowledge Asset 拼成可比较文本（白名单字段）"""
        parts = []
        for key in ("title", "tldr", "summary"):
            v = context.get(key)
            if v:
                parts.append(str(v))
        for kp in (context.get("key_points") or [])[:5]:
            parts.append(str(kp))
        for tag in (context.get("tags") or [])[:10]:
            parts.append(str(tag))
        return " ".join(parts)

    def _tokenize(self, text: str) -> set:
        """中文字符 2/3-gram + 英文词"""
        tokens = set()
        # 英文单词
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{1,}", text.lower()):
            tokens.add(word)
        # 中文 2/3-gram
        cn = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
        for n in (3, 2):
            for i in range(len(cn) - n + 1):
                tokens.add("".join(cn[i:i + n]))
        return tokens

    # 知识相关意图词（用户明确指向"这个知识"时的意图，即使无实体词也视为相关）
    KNOWLEDGE_INTENT_WORDS = [
        "这个", "这篇", "该知识", "这个知识", "这个话题", "这个内容", "这个信息",
        "总结", "概括", "详情", "详细", "具体", "关键", "要点", "细节", "参考",
        "帮助", "价值", "入手", "说了什么", "讲的", "讲的什么", "了解", "还有哪些",
        "我的", "我该", "我做决定",
    ]

    def _intent_hit(self, query: str) -> bool:
        """query 是否含知识相关意图词（指代 + 意图）"""
        return any(w in query for w in self.KNOWLEDGE_INTENT_WORDS)

    def _lexical_score(self, query: str, context_text: str) -> tuple:
        """score = 命中 query token 数 / query token 数（Jaccard 变体）

        增强: 若 query 含知识相关意图词（"总结这个知识"），
        即使无实体词重叠也视为相关（score >= 1.0）。
        """
        q_tokens = self._tokenize(query)
        c_tokens = self._tokenize(context_text)

        # 过滤过短的 token（单字中文 gram 不算）
        q_tokens = {t for t in q_tokens if len(t) >= 2}
        c_tokens = {t for t in c_tokens if len(t) >= 2}

        if not q_tokens:
            return 0.0, {"q_tokens": 0, "hits": 0}

        hits = q_tokens & c_tokens
        # 加权: 更长 token 命中更有信息量
        hit_score = sum(len(t) for t in hits)
        max_score = sum(len(t) for t in q_tokens)
        score = hit_score / max_score if max_score else 0.0

        # 意图增强: query 指向"这个知识"时视为相关（指代无法靠词面匹配）
        if self._intent_hit(query) and score < 1.0:
            score = max(score, 1.0)

        return score, {
            "q_tokens": len(q_tokens),
            "hits": sorted(hits)[:20],
            "hit_count": len(hits),
            "raw_score": round(score, 4),
            "intent_hit": self._intent_hit(query),
        }

    @staticmethod
    def _reason(decision: bool, score: float) -> str:
        if decision:
            return f"similarity={score:.2f} >= threshold，注入 context"
        return f"similarity={score:.2f} < threshold，跳过注入（query 与 context 不相关）"
