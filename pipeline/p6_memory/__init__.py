"""
P6 Memory / RAG 模块 - Mock 实现（Phase 2）
不依赖真实 chromadb / sentence-transformers。

设计与真实链路完全一致：
  P3 summary (tldr + key_points)
      ↓  embedding（mock: md5 归一化的 384 维向量）
      ↓  索引（mock: JSON 存 [{note_id, vector, text, metadata}] + 余弦相似度 top-k）
      ↓  query embedding → top-k 检索
      ↓  LLM 回答（mock: 基于检索 chunks 拼模板）
      ↓  输出 RAGResult（必须带 retrieved_note_ids）
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from schemas import (
    SummarizedNote, RAGResult,
    load_json,
)
from config import (
    path_summary, path_chroma, path_rag_result,
    RAG,
)

# ChromaDB + sentence-transformers
try:
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
except ImportError:
    # 如果未安装，mock 模式仍可工作
    pass

# 默认 embedding 维度（与 config.RAG.embedding_dim 对齐）
VEC_DIM = 384


def _chunk_text(s: SummarizedNote) -> str:
    """用于 embedding 的 chunk：tldr + tags + key_points 拼接"""
    bits = [s.tldr]
    bits.append("分类:" + s.category_l1 + "/" + s.category_l2)
    bits.append("标签:" + ",".join(s.tags))
    bits.extend(s.key_points)
    bits.append(s.actionable)
    return " | ".join(bits)


# ============================================================
# Chroma Vector Store（Phase 3）
# ============================================================
class ChromaVectorStore:
    """
    ChromaDB 封装，支持：
      - 初始化 collection（自动创建或加载）
      - upsert 单条记录（含 embedding）
      - top_k 检索
    """

    def __init__(self, root: Path, embedding_model: str = "BAAI/bge-small-zh-v1.5"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model

        # 初始化 Chroma client
        self._client = chromadb.PersistentClient(path=str(root))
        # 初始化 embedding function
        try:
            self._ef = SentenceTransformerEmbeddingFunction(model_name=embedding_model)
        except Exception as e:
            print(f"[ChromaVectorStore] 初始化 embedding model '{embedding_model}' 失败: {e!r}，回退到 'all-MiniLM-L6-v2'")
            self._ef = SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

        # 创建 collection
        self._collection = self._client.get_or_create_collection(
            name="recollect_summary",
            embedding_function=self._ef,
        )

    def upsert(self, note_id: str, text: str, metadata: Dict) -> bool:
        """upsert 单条记录，失败返回 False"""
        try:
            self._collection.upsert(
                ids=[note_id],
                documents=[text],
                metadatas=[metadata],
            )
            return True
        except Exception as e:
            print(f"[ChromaVectorStore] upsert 失败: {e!r}")
            return False

    def top_k(self, query_text: str, k: int) -> List[Tuple[float, Dict]]:
        """query → top-k 检索，返回 [(score, metadata), ...]"""
        try:
            results = self._collection.query(
                query_texts=[query_text],
                n_results=k,
                include=["distances", "metadatas"],
            )
            # 转换格式：[(distance, metadata), ...]
            if not results["ids"] or not results["metadatas"]:
                return []
            ids = results["ids"][0]
            distances = results["distances"][0]
            metadatas = results["metadatas"][0]
            scored = []
            for i, id_ in enumerate(ids):
                # Chroma 返回的是距离（越小越好），转成相似度（越大越好）
                score = 1.0 - distances[i]
                scored.append((score, metadatas[i]))
            return sorted(scored, key=lambda x: x[0], reverse=True)
        except Exception as e:
            print(f"[ChromaVectorStore] query 失败: {e!r}")
            return []


# ============================================================
# build_index / query / run
# ============================================================
def build_index(task_id: str, incremental: bool = True, **kwargs) -> Path:
    """P6 索引构建：P4 写完后随写随建（增量）"""
    summaries: List[SummarizedNote] = load_json(str(path_summary(task_id)), SummarizedNote)
    try:
        # 尝试初始化 ChromaVectorStore
        store = ChromaVectorStore(path_chroma(task_id))
        added = 0
        for s in summaries:
            chunk = _chunk_text(s)
            ok = store.upsert(
                note_id=s.note_id,
                text=chunk,
                metadata={"category_l1": s.category_l1, "category_l2": s.category_l2,
                          "title": s.title, "url": s.url},
            )
            if ok:
                added += 1
        print(f"[P6 build_index] task_id={task_id}  Chroma 构建完成，新增={added} 条  → {path_chroma(task_id).name}/")
    except Exception as exc:
        print(f"[P6 build_index] Chroma 初始化失败，回退到 mock: {exc!r}")
        # 回退到 mock
        from pipeline.p6_memory import MockVectorStore
        store = MockVectorStore(path_chroma(task_id))
        added = 0
        for s in summaries:
            chunk = _chunk_text(s)
            vec = _mock_embed(chunk)
            ok = store.upsert(
                note_id=s.note_id,
                text=chunk,
                vector=vec,
                metadata={"category_l1": s.category_l1, "category_l2": s.category_l2,
                          "title": s.title, "url": s.url},
            )
            if ok:
                added += 1
        store.save()
        print(f"[P6 build_index] task_id={task_id}  Mock 构建完成，新增={added} 条  → {path_chroma(task_id).name}/")
    return path_chroma(task_id)


def _mock_answer(query: str, chunks: List[Tuple[float, Dict]]) -> Tuple[str, str]:
    """Mock 回答生成：基于 top-k chunks 的标题/要点，结构化输出"""
    if not chunks:
        return ("抱歉，知识库中暂时没有相关内容。", "low")
    # 总结点
    titles = [it["metadata"].get("title", "（无标题）") for _, it in chunks]
    point_pool: List[str] = []
    for _, it in chunks:
        text = it["text"]
        for seg in re.split(r"[|｜]", text):
            seg = seg.strip()
            if 8 <= len(seg) <= 80:
                point_pool.append(seg)
    point_pool = list(dict.fromkeys(point_pool))[:6]

    # 置信度：基于 top1 相似度
    top1_sim = chunks[0][0]
    if top1_sim >= 0.75:
        conf = "high"
    elif top1_sim >= 0.55:
        conf = "medium"
    else:
        conf = "low"

    ans = []
    ans.append(f"根据你的问题「{query}」，我整理了 {len(chunks)} 条收藏作为参考：")
    for i, t in enumerate(titles, 1):
        ans.append(f"{i}. 《{t}》")
    if point_pool:
        ans.append("\n核心要点：")
        for i, p in enumerate(point_pool, 1):
            ans.append(f"- {p}")
    ans.append("\n（回答来源：retrieved_note_ids，详细内容可点回原文链接查看）")
    return "\n".join(ans), conf


def query(task_id: str, query_text: str,
          top_k: int | None = None,
          model_override: str | None = None,
          query_id: str = "q1",
          **kwargs) -> Path:
    """P6 检索问答：返回 RAGResult（必须带 retrieved_note_ids）"""
    k = top_k or RAG["top_k"]
    index_path = path_chroma(task_id)
    try:
        # 尝试初始化 ChromaVectorStore
        store = ChromaVectorStore(index_path)
        topk = store.top_k(query_text, k=k)
    except Exception as exc:
        print(f"[P6 query] Chroma 查询失败，回退到 mock: {exc!r}")
        # 回退到 mock
        from pipeline.p6_memory import MockVectorStore
        store = MockVectorStore(index_path)
        if store.count == 0:
            # 索引不存在：尝试立即构建
            build_index(task_id, incremental=True)
            store = MockVectorStore(index_path)
        q_vec = _mock_embed(query_text)
        topk = store.top_k(q_vec, k=k)

    retrieved_chunks = [
        {"note_id": it["note_id"], "score": round(float(sim), 4),
         "metadata": it["metadata"]}
        for sim, it in topk
    ]
    retrieved_ids = [c["note_id"] for c in retrieved_chunks]
    answer, conf = _mock_answer(query_text, topk)

    result = RAGResult(
        query=query_text,
        retrieved_note_ids=retrieved_ids,
        answer=answer,
        confidence=conf,
        retrieved_chunks=retrieved_chunks,
    )
    out = path_rag_result(task_id, query_id=query_id)
    with open(out, "w", encoding="utf-8") as f:
        f.write(result.to_json())
    extra = f"（模型覆盖={model_override}）" if model_override else ""
    print(f"[P6 query] task_id={task_id} query_id={query_id} topk={len(retrieved_ids)} conf={conf} → {out.name}{extra}")
    return out


def run(task_id: str,
        queries: Optional[List[str]] = None,
        query_file: Optional[Path] = None,
        top_k: int | None = None,
        **kwargs) -> List[Path]:
    """P6 入口：(1) 确保索引存在 (2) 批量查询"""
    # 1) 索引
    build_index(task_id, incremental=True)
    # 2) 展开 query 列表
    qs: List[str] = []
    if query_file and Path(query_file).exists():
        with open(query_file, "r", encoding="utf-8") as f:
            qs = [ln.strip() for ln in f if ln.strip()]
    if queries:
        qs.extend(list(queries))
    if not qs:
        # 无 query → 用 Demo 内置 3 个
        qs = [
            "程序员副业有哪些可以快速起步的方向？有哪些坑？",
            "上海落户的完整流程和材料清单是什么？",
            "想做数据分析，常用的 Pandas 技巧？",
        ]
    outs: List[Path] = []
    for i, q in enumerate(qs, 1):
        outs.append(query(task_id, q, top_k=top_k, query_id=f"q{i}"))
    return outs
