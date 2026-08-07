"""
Event Router（Phase 2）— 事件路由层

职责：
  读取 data/events/*.jsonl，按事件类型分流：
  - note_view（带正文）→ context_store.event_ingest（已有，零改动）
  - note_collect       → context_store.pending_store（新增 pending task）

不修改已有模块；只新增路由入口。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.context_store import pending_store  # noqa: E402
from collector.context_store.event_ingest import (  # noqa: E402
    event_to_raw, load_existing_ids,
)
from schemas import dump_jsonl  # noqa: E402


def read_event_files(events_dir: Path) -> List[Dict]:
    """读取事件目录全部 jsonl（合并去重）"""
    events = []
    if not events_dir.exists():
        return events
    for f in sorted(events_dir.glob("*.jsonl")):
        if f.name.startswith("pending_"):  # 跳过 pending 文件本身
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        events.append(json.loads(ln))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return events


def route_events(events_dir: Path, out_dir: Path) -> Dict:
    """
    路由所有事件：
    - note_view → 转 RawNote 写入 out_dir/events_{date}.jsonl（幂等）
    - note_collect → pending task
    返回统计：{view_added, view_skipped, collect_new, collect_dup, skipped}
    """
    events = read_event_files(events_dir)
    stats = {"view_added": 0, "view_skipped": 0, "collect_new": 0,
             "collect_dup": 0, "skipped": 0}

    view_notes = []
    for ev in events:
        etype = ev.get("event_type", "")
        if etype == "note_view":
            raw = event_to_raw(ev)
            if raw is not None:
                view_notes.append(raw)
            else:
                stats["view_skipped"] += 1
        elif etype == "note_collect":
            note_id = ev.get("note_id", "")
            if not note_id:
                stats["skipped"] += 1
                continue
            added = pending_store.add_pending(
                note_id=note_id,
                timestamp=ev.get("timestamp", ""),
                source=ev.get("source", "browser"),
                url=ev.get("url", ""),
                events_dir=events_dir,
            )
            stats["collect_new" if added else "collect_dup"] += 1
        else:
            stats["skipped"] += 1

    # note_view → 写 RawNote（幂等：过滤已存在 note_id）
    if view_notes:
        from datetime import datetime
        date = datetime.now().strftime("%Y%m%d")
        out_path = out_dir / f"events_{date}.jsonl"
        existing = load_existing_ids(out_path)
        seen = set(existing)
        new_notes = []
        for r in view_notes:
            if r.note_id in seen:
                continue
            seen.add(r.note_id)
            new_notes.append(r)
        if new_notes:
            dump_jsonl(str(out_path), new_notes)
        stats["view_added"] = len(new_notes)

    return stats
