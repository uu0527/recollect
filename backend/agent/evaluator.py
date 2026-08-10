"""
Evaluator - Agent 调用记录接口

第一阶段：把 Agent 调用记录追加到 eval/agent/agent_runs.jsonl
（复用 eval 目录约定；未来可接入 Eval Dashboard）。

记录内容：query / sources / answer / latency / timestamp
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

RUNS_FILE = ROOT / "eval" / "agent" / "agent_runs.jsonl"


class Evaluator:
    """Agent 调用记录器（失败不阻断主流程）"""

    def record(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        answer: str,
        latency_ms: int,
        model: str = "",
        token_usage: Dict[str, int] | None = None,
        prompt_length: int = 0,
        response_length: int = 0,
        mode: str = "plain",
        context_applied: bool = False,
        knowledge_id: str = "",
    ) -> None:
        """记录一次 Agent 调用

        mode: "plain" | "context"（Evaluation 模式标识，兼容旧数据）
        context_applied: Knowledge Context 是否真正注入
        knowledge_id: 注入的 Knowledge id（context 模式）
        """
        try:
            RUNS_FILE.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "query": query,
                "n_sources": len(sources),
                "sources": [s.get("note_id", "") for s in sources],
                "answer_preview": answer[:200],
                "latency_ms": latency_ms,
                "model": model,
                "token_usage": token_usage or {},
                "prompt_length": prompt_length,
                "response_length": response_length,
                "mode": mode,
                "context_applied": context_applied,
                "knowledge_id": knowledge_id,
            }
            with open(RUNS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass  # eval 记录失败不阻断
