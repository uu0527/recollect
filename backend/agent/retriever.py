"""
Knowledge Retriever - 检索接口

第一阶段：从 Supabase knowledge 表（经 StorageAdapter）检索；
返回 top 结果（按关键词匹配 tldr/title/tags 的简化实现）。

未来扩展：RAG 向量检索（P6 chroma / pgvector）。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.context_store.adapters import get_adapter  # noqa: E402

TOP_K = 5


def _ensure_env() -> None:
    """确保 .env 已加载（调用方未 import config 时）"""
    import os
    if os.environ.get("SUPABASE_URL"):
        return
    env_path = ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except Exception:
            pass


_ensure_env()


class Retriever:
    """knowledge 检索器"""

    def __init__(self) -> None:
        self._adapter = get_adapter()

    def retrieve(self, query: str, top_k: int = TOP_K) -> List[Dict[str, Any]]:
        """按 query 检索 knowledge，返回 top_k 条（简化实现）

        MVP：关键词打分（query 分词命中 title/tldr/tags 加分）。
        """
        try:
            cards = self._list_all_cards()
        except Exception:
            return []
        if not cards:
            return []

        q_terms = self._tokenize(query)
        scored = []
        for c in cards:
            score = self._score_card(c, q_terms)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        results = [self._to_source(c) for _, c in scored[:top_k]]
        return results

    # ------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------
    def _list_all_cards(self) -> List[Dict]:
        """列出全部 knowledge（adapter 目前只有按 note_id 查询，
        MVP 先走 adapter.get_knowledge 探测 + 直接 SQL 兜底）。"""
        # 尝试直接 SQL（adapter 无 list_knowledge 接口）
        try:
            from supabase import create_client
            import os
            client = create_client(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", ""))
            resp = client.table("knowledge").select("*").limit(200).execute()
            return resp.data or []
        except Exception:
            pass
        # 兜底：adapter 接口（返回空）
        return []

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """简单分词：中文按词（2-4 字滑窗）+ 英文单词"""
        tokens = set()
        # 英文单词
        for word in text.lower().split():
            if word.isascii() and len(word) > 1:
                tokens.add(word)
        # 中文：用 2/3 字滑窗（避免单个 bigram 误匹配）
        cn = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
        for n in (3, 2):
            for i in range(len(cn) - n + 1):
                tokens.add("".join(cn[i:i + n]))
        return list(tokens)

    def _score_card(self, card: Dict, q_terms: List[str]) -> float:
        """打分：精确命中 title(×3) / tldr(×2) / tags(×2)。
        要求至少 2 个不同词命中（避免单个 bigram 误匹配）。"""
        title = card.get("title", "") or ""
        tldr = card.get("tldr", "") or ""
        tags = " ".join(card.get("tags", []) or [])
        hit_terms = set()
        score = 0.0
        for t in q_terms:
            hit = False
            if t in title:
                score += 3
                hit = True
            if t in tldr:
                score += 2
                hit = True
            if t in tags:
                score += 2
                hit = True
            if hit:
                hit_terms.add(t)
        # 至少 2 个不同词命中才返回（相关性门槛）
        return score if len(hit_terms) >= 2 else 0.0

    @staticmethod
    def _to_source(card: Dict) -> Dict[str, Any]:
        return {
            "note_id": card.get("note_id", ""),
            "title": card.get("title", ""),
            "url": card.get("url", ""),
            "category_l1": card.get("category_l1", ""),
            "tldr": card.get("tldr", ""),
        }
