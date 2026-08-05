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

# 默认 embedding 维度（与 config.RAG.embedding_dim 对齐）
VEC_DIM = 384


# ============================================================
# Mock Embedding：稳定、可重复、基于 MD5 种子
# ============================================================
def _mock_embed(text: str, dim: int = VEC_DIM) -> List[float]:
    """将任意文本映射为单位 L2 向量（可重复）"""
    vec: List[float] = [0.0] * dim
    if not text:
        # 零向量归一化 fallback
        vec[0] = 1.0
        return vec
    # 用 MD5 的 16 字节流 + 多轮 double 填充
    h = hashlib.md5(text.encode("utf-8")).digest()
    # 扩展为 dim 个数字：按 4 字节拼成 float，做 tanh 归一
    seed_bytes = h * ((dim * 4 // len(h)) + 2)
    for i in range(dim):
        chunk = seed_bytes[i*4:(i+1)*4]
        v = struct.unpack("<I", chunk)[0]
        # 映射到 [-1, 1]
        normalized = (v / 0xFFFFFFFF) * 2.0 - 1.0
        normalized = math.tanh(normalized * 1.5)
        # 混入 token 特征：让语义相近词的向量有偏置
        if i < len(text):
            ch = ord(text[i % len(text)])
            normalized += 0.08 * math.sin((ch % 17) * 0.37 + i)
        vec[i] = normalized
    # L2 归一
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


# ============================================================
# Mock Vector Store（模拟 Chroma）
# ============================================================
class MockVectorStore:
    """按 note_id 存储 embedding + chunk 文本；支持增量 upsert"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store_path = self.root / "store.json"
        self._items: Dict[str, Dict] = {}
        if self.store_path.exists():
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    self._items = {it["note_id"]: it for it in raw}
            except Exception:
                self._items = {}

    @property
    def count(self) -> int:
        return len(self._items)

    def upsert(self, note_id: str, text: str, vector: List[float],
               metadata: Dict) -> bool:
        """增量：已存在不重复存储。返回是否新插入。"""
        if note_id in self._items:
            return False
        self._items[note_id] = {
            "note_id": note_id,
            "text": text,
            "vector": vector,
            "metadata": metadata,
        }
        return True

    def save(self) -> None:
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(list(self._items.values()), f, ensure_ascii=False, indent=2)

    def top_k(self, q_vec: List[float], k: int) -> List[Tuple[float, Dict]]:
        scored = []
        for it in self._items.values():
            sim = _cosine(q_vec, it["vector"])
            scored.append((sim, it))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:k]


def _chunk_text(s: SummarizedNote) -> str:
    """用于 embedding 的 chunk：tldr + tags + key_points 拼接"""
    bits = [s.tldr]
    bits.append("分类:" + s.category_l1 + "/" + s.category_l2)
    bits.append("标签:" + ",".join(s.tags))
    bits.extend(s.key_points)
    bits.append(s.actionable)
    return " | ".join(bits)


# ============================================================
# build_index / query / run
# ============================================================
def build_index(task_id: str, incremental: bool = True, **kwargs) -> Path:
    """P6 索引构建：P4 写完后随写随建（增量）"""
    summaries: List[SummarizedNote] = load_json(str(path_summary(task_id)), SummarizedNote)
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
    print(f"[P6 build_index] task_id={task_id}  总量={store.count}  新增={added}  增量={incremental}  → {path_chroma(task_id).name}/")
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
