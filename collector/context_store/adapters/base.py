"""
Storage Adapter - 抽象基类

设计原则：pipeline 不感知底层存储（file / supabase）。
所有存储操作通过 StorageAdapter 接口访问。

最小接口（Alpha MVP P0）：
  Event:     add_event() / list_events()
  Knowledge: upsert_knowledge() / get_knowledge_by_note_id()
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class StorageAdapter(ABC):
    """存储适配器统一接口（pipeline 只依赖此抽象）"""

    name: str = "base"

    # ============================================================
    # Event
    # ============================================================
    @abstractmethod
    def add_event(self, event: Dict) -> bool:
        """写入一条原始事件，返回是否新增"""

    @abstractmethod
    def list_events(self, limit: int = 100) -> List[Dict]:
        """列出最近事件（新→旧）"""

    # ============================================================
    # Knowledge
    # ============================================================
    @abstractmethod
    def upsert_knowledge(self, card: Dict) -> bool:
        """写入/更新知识卡片（note_id 幂等）"""

    @abstractmethod
    def get_knowledge_by_note_id(self, note_id: str) -> Optional[Dict]:
        """按 note_id 查询知识卡片"""


def get_adapter() -> StorageAdapter:
    """按环境变量选择存储后端（默认 file，保证现有测试不受影响）

    兜底加载 .env（调用方可能未 import config/load_dotenv）。
    """
    import os
    from pathlib import Path

    if os.environ.get("STORAGE_BACKEND") is None:
        # 尝试加载项目根 .env（静默失败：无文件时保持默认 file）
        env_path = Path(__file__).resolve().parent.parent.parent.parent / ".env"
        if env_path.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path)
            except Exception:
                pass

    backend = os.environ.get("STORAGE_BACKEND", "file").strip().lower()
    if backend == "supabase":
        from collector.context_store.adapters.supabase_adapter import SupabaseStorageAdapter
        return SupabaseStorageAdapter()
    from collector.context_store.adapters.file_adapter import FileStorageAdapter
    return FileStorageAdapter()
