"""
Prompt Builder - 上下文构造

把 query + knowledge 检索结果 + 用户记忆 → 结构化 prompt dict。
（不直接拼 LLM 字符串；由调用方决定如何序列化）
"""
from __future__ import annotations

from typing import Any, Dict, List


class PromptBuilder:
    """构造 Agent 对话上下文"""

    def build(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        memory: Dict[str, Any],
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
        return context

    def to_llm_text(self, ctx: Dict[str, Any]) -> str:
        """把结构化上下文序列化为 LLM prompt 文本（后续接入真实 LLM 时用）"""
        lines = [f"用户问题: {ctx['query']}", "", "相关知识:"]
        for s in ctx["sources"]:
            lines.append(f"- [{s['category']}] {s['title']}: {s['tldr']}")
        if ctx["user_memory"]["topics"]:
            lines.append("")
            lines.append(f"用户感兴趣主题: {', '.join(ctx['user_memory']['topics'])}")
        return "\n".join(lines)
