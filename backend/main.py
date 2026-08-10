"""
ReCollect Agent Backend - FastAPI 启动入口

启动:
  .venv/Scripts/python.exe -m uvicorn backend.main:app --reload --port 8000
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.chat import router as chat_router

app = FastAPI(
    title="ReCollect Agent API",
    description="ReCollect Agent Backend（Chatbot / Memory / Eval 统一入口）",
    version="0.1.0",
)

# CORS：允许前端静态页跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Alpha MVP 阶段放开；后续收紧
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")


@app.get("/health")
def health() -> dict:
    """健康检查"""
    return {"status": "ok", "service": "recollect-agent-backend"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
