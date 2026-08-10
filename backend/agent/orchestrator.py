"""
Agent Orchestrator - 流程编排入口

流程：
  用户请求 → retriever（knowledge 检索）→ memory（用户记忆）
  → prompt_builder（构造上下文）→ LLM（预留接口）→ evaluator（记录）

第一阶段：retriever / memory / prompt_builder / evaluator 均为接口实现；
LLM 调用用 mock（不强绑定模型，接入点清晰）。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from backend.agent.evaluator import Evaluator
from backend.agent.memory import MemoryClient
from backend.agent.prompt_builder import PromptBuilder
from backend.agent.retriever import Retriever


class AgentOrchestrator:
    """Agent 编排器：串联检索 → 记忆 → 上下文 → LLM → 评估"""

    def __init__(self) -> None:
        self.retriever = Retriever()
        self.memory = MemoryClient()
        self.prompt_builder = PromptBuilder()
        self.evaluator = Evaluator()

    def handle(self, query: str, session_id: str | None = None) -> Dict[str, Any]:
        """处理一次用户请求，返回 {answer, sources, metadata}"""
        started = time.time()

        # 1. 检索 knowledge（当前：接口实现，返回 top 结果）
        sources = self.retriever.retrieve(query)

        # 2. 用户记忆（当前：调用已有 memory 模块接口）
        memory = self.memory.get_context(session_id=session_id)

        # 3. 构造上下文（含知识 + 记忆 → prompt）
        prompt = self.prompt_builder.build(
            query=query, sources=sources, memory=memory
        )

        # 4. LLM 调用（预留接口，第一阶段 mock）
        answer = self._call_llm(prompt)

        # 5. 评估记录（接口：写 eval 记录，失败不阻断）
        self.evaluator.record(
            query=query, sources=sources, answer=answer, latency_ms=int((time.time() - started) * 1000)
        )

        return {
            "answer": answer,
            "sources": sources,
            "metadata": {
                "session_id": session_id,
                "latency_ms": int((time.time() - started) * 1000),
                "n_sources": len(sources),
                "llm_provider": self._llm_provider_name(),
            },
        }

    # ------------------------------------------------------------
    # LLM 预留接口：第一阶段 mock；后续接入 pipeline/_llm router
    # ------------------------------------------------------------
    def _call_llm(self, prompt: Dict[str, Any]) -> str:
        """调用 LLM 生成回答。

        当前：mock 回答（避免真实 API 调用与成本）。
        后续接入真实模型：用 pipeline/_llm/router.get_stage_provider，
        把 prompt 传入 provider.complete() 即可（见 README 说明）。
        """
        query = prompt.get("query", "")
        n_sources = len(prompt.get("sources", []))
        return (
            f"[mock] 已收到你的问题：「{query}」。"
            f"检索到 {n_sources} 条相关知识。"
            "Agent Backend 骨架已就绪，真实 LLM 将在下一阶段接入。"
        )

    @staticmethod
    def _llm_provider_name() -> str:
        return "mock"
