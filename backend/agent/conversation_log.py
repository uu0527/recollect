"""
Conversation Logger - 对话日志记录（Alpha MVP）

为未来 Analysis Skill 预留数据接口（本阶段只记录，不分析）。

记录内容（每轮对话追加一行 JSON）:
  {
    "timestamp": "...",
    "session_id": "...",
    "query": "...",
    "answer_preview": "...",
    "retrieved_context": bool,       # 是否携带 knowledge context 请求
    "router_decision": bool,         # Router 是否决定注入
    "router_score": float,
    "sources": [...],                # 回答引用的 knowledge
    "tokens": int,
    "latency_ms": int,
    "model": "..."
  }

存储: data/conversations/conversations.jsonl
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LOG_DIR = ROOT / "data" / "conversations"
LOG_FILE = LOG_DIR / "conversations.jsonl"


class ConversationLogger:
    """对话日志记录器（失败不阻断主流程）"""

    def log(self, entry: Dict[str, Any]) -> None:
        """记录一轮对话（失败静默，不影响 Agent 回答）"""
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "session_id": entry.get("session_id"),
                "query": entry.get("query", ""),
                "answer_preview": (entry.get("answer") or "")[:200],
                "retrieved_context": bool(entry.get("retrieved_context")),
                "router_decision": entry.get("router_decision"),
                "router_score": entry.get("router_score"),
                "context_error": entry.get("context_error"),  # context 解析失败原因（可为 null）
                "sources": [s.get("note_id", "") for s in entry.get("sources", [])],
                "source_titles": [s.get("title", "") for s in entry.get("sources", [])][:5],
                "tokens": entry.get("tokens", 0),
                "latency_ms": entry.get("latency_ms", 0),
                "model": entry.get("model", ""),
            }
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 日志失败不阻断
