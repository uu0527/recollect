"""
Storage Adapter - Supabase (PostgreSQL) 实现（生产）

依赖：supabase-py（pip install supabase）
配置：SUPABASE_URL / SUPABASE_KEY（见 .env.example）

失败策略：Supabase 不可用时打 WARNING 并返回 False（不阻断 pipeline，
与 sync_pipeline 的"失败不阻断"原则一致）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

if str(Path(__file__).resolve().parent.parent.parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from collector.context_store.adapters.base import StorageAdapter  # noqa: E402


def _client():
    """惰性创建 supabase client（未配置 key 时返回 None）"""
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        print("[supabase] WARNING: SUPABASE_URL/SUPABASE_KEY 未配置，Supabase 不可用")
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except ImportError:
        print("[supabase] WARNING: 未安装 supabase 包（pip install supabase）")
        return None
    except Exception as exc:
        print(f"[supabase] WARNING: 客户端创建失败: {exc}")
        return None


class SupabaseStorageAdapter(StorageAdapter):
    """Supabase 存储适配器（events / knowledge 表）"""

    name = "supabase"

    # ------------------------------------------------------------
    # Event
    # ------------------------------------------------------------
    def add_event(self, event: Dict) -> bool:
        client = _client()
        if client is None:
            return False
        try:
            row = {
                "event_type": event.get("event_type", ""),
                "note_id": event.get("note_id", ""),
                "url": event.get("url", ""),
                "title": event.get("title", ""),
                "content": event.get("content", ""),
                "images": event.get("images", []) or [],
                "author": event.get("author", ""),
                "payload": event,  # 完整原始事件
            }
            # 幂等：同 note_id+event_type 已存在则不重复插入
            existing = (client.table("events")
                        .select("id")
                        .eq("note_id", row["note_id"])
                        .eq("event_type", row["event_type"])
                        .limit(1)
                        .execute())
            if existing.data:
                return False
            client.table("events").insert(row).execute()
            return True
        except Exception as exc:
            print(f"[supabase] WARNING: add_event 失败: {exc}")
            return False

    def list_events(self, limit: int = 100) -> List[Dict]:
        client = _client()
        if client is None:
            return []
        try:
            resp = (client.table("events")
                    .select("*")
                    .order("created_at", desc=True)
                    .limit(limit)
                    .execute())
            return resp.data or []
        except Exception as exc:
            print(f"[supabase] WARNING: list_events 失败: {exc}")
            return []

    # ------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------
    def upsert_knowledge(self, card: Dict) -> bool:
        client = _client()
        if client is None:
            return False
        try:
            row = {
                "note_id": card.get("note_id", ""),
                "title": card.get("title", ""),
                "url": card.get("url", ""),
                "category_l1": card.get("category_l1", ""),
                "category_l2": card.get("category_l2", ""),
                "tags": card.get("tags", []) or [],
                "tldr": card.get("tldr", ""),
                "key_points": card.get("key_points", []) or [],
                "actionable": card.get("actionable", ""),
                "content_type": card.get("content_type", ""),
                "raw_content": card.get("raw_content", ""),
                "images": card.get("images", []) or [],
                "quality_flags": card.get("quality_flags", []) or [],
            }
            # upsert：note_id UNIQUE → on_conflict 更新
            client.table("knowledge").upsert(row, on_conflict="note_id").execute()
            return True
        except Exception as exc:
            print(f"[supabase] WARNING: upsert_knowledge 失败: {exc}")
            return False

    def get_knowledge_by_note_id(self, note_id: str) -> Optional[Dict]:
        client = _client()
        if client is None:
            return None
        try:
            resp = (client.table("knowledge")
                    .select("*")
                    .eq("note_id", note_id)
                    .limit(1)
                    .execute())
            return resp.data[0] if resp.data else None
        except Exception as exc:
            print(f"[supabase] WARNING: get_knowledge_by_note_id 失败: {exc}")
            return None
