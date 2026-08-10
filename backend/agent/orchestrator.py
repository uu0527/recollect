"""
Agent Orchestrator - 流程编排入口

流程：
  用户请求 → retriever（knowledge 检索）→ memory（用户记忆）
  → prompt_builder（构造上下文）→ LLM（真实，复用 pipeline router）
  → evaluator（记录）

第二阶段：接入真实 LLM（复用 pipeline/_llm/router 的 provider 机制，
不新增模型调用体系）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.evaluator import Evaluator
from backend.agent.memory import MemoryClient
from backend.agent.prompt_builder import PromptBuilder
from backend.agent.retriever import Retriever

# LLM system prompt（Agent 角色设定）
SYSTEM_PROMPT = (
    "你是 ReCollect 个人知识 Agent。基于用户收藏的知识卡片（sources）回答问题。"
    "如果 sources 中有相关知识，必须引用其内容作答；若没有相关知识，诚实说明，"
    "并基于通用知识简要回答。回答简洁、结构化、用中文。"
)


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

        # 1. 检索 knowledge
        sources = self.retriever.retrieve(query)

        # 2. 用户记忆
        memory = self.memory.get_context(session_id=session_id)

        # 3. 构造上下文
        prompt = self.prompt_builder.build(
            query=query, sources=sources, memory=memory
        )

        # 4. 真实 LLM 调用（复用 pipeline router；失败降级 mock 不阻断）
        answer, llm_info = self._call_llm(prompt)

        latency_ms = int((time.time() - started) * 1000)

        # 5. 评估记录（含 model/token usage/prompt length/response length）
        self.evaluator.record(
            query=query,
            sources=sources,
            answer=answer,
            latency_ms=latency_ms,
            model=llm_info.get("model", ""),
            token_usage=llm_info.get("token_usage", {}),
            prompt_length=llm_info.get("prompt_chars", 0),
            response_length=len(answer),
        )

        return {
            "answer": answer,
            "sources": sources,
            "metadata": {
                "session_id": session_id,
                "latency_ms": latency_ms,
                "source_count": len(sources),
                "llm_provider": llm_info.get("provider", "mock"),
                "token_usage": llm_info.get("token_usage", {}),
            },
        }

    # ------------------------------------------------------------
    # LLM 调用（复用 pipeline/_llm/router，不新增模型体系）
    # ------------------------------------------------------------
    def _call_llm(self, prompt: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """调用真实 LLM。

        复用 pipeline/_llm/router.get_stage_provider（自动按复杂度分级、
        key 校验、降级到可用模型、token 统计）。
        """
        try:
            from pipeline._llm.router import get_stage_provider

            user_text = self.prompt_builder.to_llm_text(prompt)
            provider = get_stage_provider(
                stage="chat",
                task_id="agent_backend",
                task_type="qa",
                text=prompt.get("query", ""),
            )

            answer = provider.complete(SYSTEM_PROMPT, user_text)

            # 真实 token usage（TrackedLLMClient 包装的 inner 有 _last_usage）
            usage = self._extract_usage(provider)
            return answer, {
                "provider": getattr(provider, "provider_name", "unknown"),
                "model": getattr(provider, "model", ""),
                "token_usage": usage,
                "prompt_chars": len(user_text),
            }
        except Exception as exc:
            # 真实 LLM 失败 → 降级 mock（不阻断），并记录原因
            query = prompt.get("query", "")
            n_sources = len(prompt.get("sources", []))
            fallback = (
                f"[fallback] 你的问题：「{query}」。"
                f"检索到 {n_sources} 条相关知识。"
                f"（真实 LLM 暂不可用: {type(exc).__name__}）"
            )
            return fallback, {
                "provider": "mock",
                "model": "mock",
                "token_usage": {},
                "prompt_chars": 0,
                "error": str(exc),
            }

    @staticmethod
    def _extract_usage(provider: Any) -> Dict[str, Any]:
        """从 provider 提取真实 token usage"""
        inner = getattr(provider, "_inner", None)
        last = getattr(inner, "_last_usage", None) or {}
        return {
            "input_tokens": last.get("input_tokens", 0),
            "output_tokens": last.get("output_tokens", 0),
            "total_tokens": last.get("total_tokens", 0),
        }
