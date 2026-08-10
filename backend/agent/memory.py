"""
Memory Client - 用户记忆调用封装

封装已有 collector/memory_builder（不重写）：
- get_context: 读取 user_memory.json，返回给 Agent 做上下文
- 未来扩展: user_memory 表入库后从 Supabase 读
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import MEMORY_DATA_DIR  # noqa: E402

USER_MEMORY_FILE = MEMORY_DATA_DIR / "user_memory.json"


class MemoryClient:
    """Agent 侧用户记忆封装（复用 memory_builder 产物）"""

    def get_context(self, session_id: str | None = None) -> Dict[str, Any]:
        """读取用户记忆，返回可注入 prompt 的上下文片段"""
        memory = self._load_user_memory()
        return {
            "topics": memory.get("topics", []),
            "preferences": memory.get("preferences", {}),
            "stats": memory.get("stats", {}),
            "updated_at": memory.get("updated_at", ""),
            "session_id": session_id,
        }

    # ------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------
    def _load_user_memory(self) -> Dict[str, Any]:
        """读 user_memory.json；不存在/损坏返回空"""
        if not USER_MEMORY_FILE.exists():
            return {}
        try:
            import json
            return json.loads(USER_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
