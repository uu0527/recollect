"""
Prompt Builder - 上下文构造

把 query + knowledge 检索结果 + 用户记忆 → 结构化 prompt dict。
（不直接拼 LLM 字符串；由调用方决定如何序列化）
"""
from __future__ import annotations

from typing import Any, Dict, List


class PromptBuilder:
    """构造 Agent 对话上下文"""

    # 长度控制：最多注入 1 个 asset；key_points ≤3；summary 截断
    MAX_CONTEXT_ASSETS = 1
    MAX_KEY_POINTS = 3
    SUMMARY_MAX_CHARS = 400

    def build(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        memory: Dict[str, Any],
        context_assets: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """返回结构化 prompt 上下文"""
        context = {
            "query": query,
            "sources": [
                {
                    "title": s.get("title", ""),
                    "category": s.get("category_l1", ""),
                    "tldr": s.get("tldr", ""),
                    "url": s.get("url", ""),
                }
                for s in sources
            ],
            "user_memory": {
                "topics": [t.get("name") for t in memory.get("topics", [])][:5],
                "preferences": memory.get("preferences", {}),
            },
        }
        # Knowledge Context 注入（short-term 任务上下文，可选）
        if context_assets:
            context["knowledge_context"] = [
                self._sanitize_asset(a) for a in context_assets[: self.MAX_CONTEXT_ASSETS]
            ]
        return context

    @staticmethod
    def _sanitize_asset(asset: Dict[str, Any]) -> Dict[str, Any]:
        """白名单字段注入：title / summary(tldr) / key_points / tags
        raw_content 默认不注入（避免 prompt 膨胀）。"""
        summary = str(asset.get("tldr") or asset.get("summary") or "")[: PromptBuilder.SUMMARY_MAX_CHARS]
        key_points = (asset.get("key_points") or [])[: PromptBuilder.MAX_KEY_POINTS]
        return {
            "title": asset.get("title", ""),
            "summary": summary,
            "key_points": key_points,
            "tags": asset.get("tags", []) or [],
        }

    def to_llm_text(self, ctx: Dict[str, Any]) -> str:
        """把结构化上下文序列化为 LLM prompt 文本"""
        lines = [f"用户问题: {ctx['query']}", "", "相关知识:"]
        for s in ctx["sources"]:
            lines.append(f"- [{s['category']}] {s['title']}: {s['tldr']}")
        if ctx["user_memory"]["topics"]:
            lines.append("")
            lines.append(f"用户感兴趣主题: {', '.join(ctx['user_memory']['topics'])}")
        # Knowledge Context 区块（存在才注入）
        for kn in ctx.get("knowledge_context", []):
            lines.append("")
            lines.append("Current Knowledge Context:")
            lines.append(f"Title: {kn['title']}")
            if kn["summary"]:
                lines.append(f"Summary: {kn['summary']}")
            if kn["key_points"]:
                lines.append("Key Points:")
                for i, kp in enumerate(kn["key_points"], 1):
                    lines.append(f"{i}. {kp}")
            if kn["tags"]:
                lines.append(f"Tags: {', '.join(kn['tags'])}")
        return "\n".join(lines)
