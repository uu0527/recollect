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

    def handle(
        self,
        query: str,
        session_id: str | None = None,
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """处理一次用户请求，返回 {answer, sources, metadata}

        context（可选）: {"knowledge_id": str} → Knowledge Context 注入
        - 无 context: 保持普通 Chat（retriever → memory → prompt → LLM）
        - 有 context: 先 Resolver 取 Knowledge Asset，再注入 prompt
        """
        started = time.time()

        # 0. Knowledge Context Resolver（可选，short-term 任务上下文）
        context_assets = self._resolve_context(context)

        # 1. 检索 knowledge
        sources = self.retriever.retrieve(query)

        # 2. 用户记忆（long-term，不受 context 影响）
        memory = self.memory.get_context(session_id=session_id)

        # 3. 构造上下文（含 Knowledge Context 注入）
        prompt = self.prompt_builder.build(
            query=query,
            sources=sources,
            memory=memory,
            context_assets=context_assets,
        )

        # 4. 真实 LLM 调用（复用 pipeline router；失败降级 mock 不阻断）
        answer, llm_info = self._call_llm(prompt)

        latency_ms = int((time.time() - started) * 1000)

        # 5. 评估记录（含 model/token usage/prompt length/response length）
        context_applied = len(context_assets) > 0
        self.evaluator.record(
            query=query,
            sources=sources,
            answer=answer,
            latency_ms=latency_ms,
            model=llm_info.get("model", ""),
            token_usage=llm_info.get("token_usage", {}),
            prompt_length=llm_info.get("prompt_chars", 0),
            response_length=len(answer),
            mode="context" if context else "plain",
            context_applied=context_applied,
            knowledge_id=(context or {}).get("knowledge_id", "") if context else "",
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
                # Context 注入追踪（eval 用）
                "context_applied": context_applied,
                "context_knowledge_id": context.get("knowledge_id") if context else None,
            },
        }

    # ------------------------------------------------------------
    # Knowledge Context Resolver
    # ------------------------------------------------------------
    def _resolve_context(self, context: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        """knowledge_id → Knowledge Asset（复用 StorageAdapter，不绕过）

        输入: {"knowledge_id": "..."}
        输出: [asset]（0 或 1 条；缺失/失败 → 空列表 → 忽略 context 继续普通 Chat）
        """
        if not context:
            return []
        knowledge_id = context.get("knowledge_id")
        if not knowledge_id:
            return []
        try:
            # 复用 StorageAdapter（get_adapter 按 STORAGE_BACKEND 选择 file/supabase）
            from collector.context_store.adapters import get_adapter
            adapter = get_adapter()
            # knowledge 表以 note_id 为主键；knowledge_id 直接映射 note_id
            card = adapter.get_knowledge_by_note_id(knowledge_id)
            if not card:
                print(f"[context] WARNING: knowledge_id={knowledge_id} 不存在，忽略 context")
                return []
            return [card]
        except Exception as exc:
            print(f"[context] WARNING: Knowledge Context 解析失败: {exc}")
            return []  # 查询失败不阻断用户请求

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
