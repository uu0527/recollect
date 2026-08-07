"""
Pending Collection Task 存储（Phase 2）
- note_collect 事件 → pending task（note_id/timestamp/source）
- JSONL 存储，note_id 幂等
- 不修改 event_ingest / note_view 链路
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pending_path(events_dir: Path | None = None) -> Path:
    """pending task 文件：data/events/pending_collect_tasks.jsonl"""
    base = events_dir or (ROOT / "data" / "events")
    return base / "pending_collect_tasks.jsonl"


def load_pending(events_dir: Path | None = None) -> List[Dict]:
    p = pending_path(events_dir)
    tasks = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                tasks.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return tasks


def add_pending(note_id: str, timestamp: str, source: str = "browser",
                url: str = "", events_dir: Path | None = None) -> bool:
    """新增 pending task（note_id 幂等：已存在则忽略）"""
    if not note_id:
        return False
    tasks = load_pending(events_dir)
    if any(t.get("note_id") == note_id for t in tasks):
        return False  # 已存在
    tasks.append({
        "note_id": note_id,
        "timestamp": timestamp or datetime.now().isoformat(),
        "source": source,
        "url": url,
        "status": "pending",   # pending → resolved / skipped
        "created_at": datetime.now().isoformat(timespec="seconds"),
    })
    p = pending_path(events_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for t in tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return True


def update_pending(note_id: str, status: str, events_dir: Path | None = None) -> bool:
    """更新 pending task 状态（resolved=已入库 / skipped=无法解析）"""
    tasks = load_pending(events_dir)
    changed = False
    for t in tasks:
        if t.get("note_id") == note_id and t.get("status") != status:
            t["status"] = status
            t["resolved_at"] = datetime.now().isoformat(timespec="seconds")
            changed = True
    if changed:
        p = pending_path(events_dir)
        with open(p, "w", encoding="utf-8") as f:
            for t in tasks:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")
    return changed


def pending_count(events_dir: Path | None = None) -> int:
    return sum(1 for t in load_pending(events_dir) if t.get("status") == "pending")
