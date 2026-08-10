"""
ReCollect Agent Backend - Chat API 入口

POST /api/chat
  输入: {query: str, session_id?: str}
  输出: {answer, sources, metadata}

第一阶段：mock answer（验证 Frontend → API → Agent Layer 链路）。
真实 LLM 接入点在 backend/agent/orchestrator.py。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.agent.orchestrator import AgentOrchestrator

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """用户对话入口（Agent Orchestrator 编排）"""
    result = AgentOrchestrator().handle(
        query=req.query,
        session_id=req.session_id,
    )
    return ChatResponse(
        answer=result["answer"],
        sources=result["sources"],
        metadata=result["metadata"],
    )
