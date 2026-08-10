"""
Context Router - 包定义

决策层：根据 query 与 retrieved context 的相关性，决定是否注入 Knowledge Context。

架构:
  Retriever → Context Router → Context Injection → LLM

Router V1 策略: Lexical Similarity（token 重叠 + 实体命中）
  - 可解释、零依赖、低成本 baseline
  - 未来可无缝切换 Embedding Similarity（接口已预留）
"""
from backend.agent.context_router.router import ContextRouter, RouterDecision

__all__ = ["ContextRouter", "RouterDecision"]
