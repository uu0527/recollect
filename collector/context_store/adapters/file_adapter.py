"""
Storage Adapter - File 实现（本地开发/测试默认）

存储位置：
  events    → data/events/storage_events.jsonl
  knowledge → data/01_raw/knowledge_cards.jsonl
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.context_store.adapters.base import StorageAdapter  # noqa: E402

EVENTS_FILE = ROOT / "data" / "events" / "storage_events.jsonl"
KNOWLEDGE_FILE = ROOT / "data" / "01_raw" / "knowledge_cards.jsonl"


def _append_jsonl(path: Path, obj: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return rows


class FileStorageAdapter(StorageAdapter):
    """文件存储适配器（JSONL 追加，幂等去重）"""

    name = "file"

    # ------------------------------------------------------------
    # Event
    # ------------------------------------------------------------
    def add_event(self, event: Dict) -> bool:
        # 幂等：同 note_id + event_type + timestamp 去重
        rows = _read_jsonl(EVENTS_FILE)
        key = (event.get("note_id"), event.get("event_type"), event.get("timestamp"))
        if any((r.get("note_id"), r.get("event_type"), r.get("timestamp")) == key for r in rows):
            return False
        row = dict(event)
        row.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        _append_jsonl(EVENTS_FILE, row)
        return True

    def list_events(self, limit: int = 100) -> List[Dict]:
        rows = _read_jsonl(EVENTS_FILE)
        return list(reversed(rows))[:limit]

    # ------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------
    def upsert_knowledge(self, card: Dict) -> bool:
        rows = _read_jsonl(KNOWLEDGE_FILE)
        note_id = card.get("note_id", "")
        kept = [r for r in rows if r.get("note_id") != note_id]  # 幂等：覆盖旧记录
        row = dict(card)
        row.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
        row["updated_at"] = datetime.now().isoformat(timespec="seconds")
        kept.append(row)
        KNOWLEDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
            for r in kept:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return True

    def get_knowledge_by_note_id(self, note_id: str) -> Optional[Dict]:
        for r in _read_jsonl(KNOWLEDGE_FILE):
            if r.get("note_id") == note_id:
                return r
        return None
