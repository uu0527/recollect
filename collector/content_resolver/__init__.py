"""
Content Resolver（Phase 2）— 解析 pending collection task 的内容

职责：
  接收 pending task（note_id/timestamp/source），尝试获取对应笔记内容：
  1. 从 data/01_raw/ 已入库 RawNote 匹配（用户可能先浏览后收藏）
  2. 从 data/events/ 近期 note_view 事件匹配（同一事件文件内）
  3. 匹配到 → 转 RawNote 写入 data/01_raw/（幂等），pending → resolved
  4. 未匹配 → pending 保持（等待后续浏览补全），不丢

不修改 event_ingest / note_view 链路。
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

from schemas import RawNote, dump_jsonl  # noqa: E402
from collector.context_store import pending_store  # noqa: E402


def _load_view_events(events_dir: Path) -> Dict[str, Dict]:
    """从 data/events/*.jsonl 收集 note_view 事件（note_id → event）"""
    result: Dict[str, Dict] = {}
    if not events_dir.exists():
        return result
    for f in sorted(events_dir.glob("*.jsonl")):
        if f.name.startswith("pending_"):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        ev = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    if ev.get("event_type") == "note_view" and ev.get("note_id") and ev.get("content"):
                        result[ev["note_id"]] = ev
        except OSError:
            continue
    return result


def _load_existing_raw(out_dir: Path) -> Dict[str, Dict]:
    """从 data/01_raw/ 收集已入库 RawNote（note_id → dict）"""
    result: Dict[str, Dict] = {}
    if not out_dir.exists():
        return result
    for f in sorted(out_dir.glob("*.jsonl")):
        try:
            with open(f, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        d = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    if d.get("note_id") and d.get("content"):
                        result[d["note_id"]] = d
        except OSError:
            continue
    return result


def resolve_pending(events_dir: Path, out_dir: Path) -> Dict:
    """
    解析所有 pending task：
    - 匹配到内容 → RawNote 写入 out_dir（幂等），pending → resolved
    - 未匹配 → 保持 pending
    返回 {resolved, still_pending, no_content}
    """
    tasks = pending_store.load_pending(events_dir)
    pending = [t for t in tasks if t.get("status") == "pending"]
    if not pending:
        return {"resolved": 0, "still_pending": 0, "no_content": 0}

    view_events = _load_view_events(events_dir)
    existing_raw = _load_existing_raw(out_dir)

    date = datetime.now().strftime("%Y%m%d")
    out_path = out_dir / f"events_{date}.jsonl"

    resolved = 0
    no_content = 0
    new_notes: List[RawNote] = []

    # 已入库 note_id（含本文件）——避免与 router 写入冲突
    existing_ids = set(existing_raw.keys())

    for task in pending:
        note_id = task["note_id"]
        # 1) 已有 RawNote 内容
        src = existing_raw.get(note_id)
        # 2) 近期 note_view 事件
        if not src:
            ev = view_events.get(note_id)
            if ev:
                src = {
                    "note_id": note_id,
                    "url": ev.get("url", ""),
                    "title": ev.get("title", ""),
                    "content": ev.get("content", ""),
                    "images": ev.get("images", []),
                    "metadata": {
                        "source": "browser_event",
                        "author": ev.get("author", ""),
                        "event_timestamp": ev.get("timestamp", ""),
                        "event_type": "note_collect_resolved",
                    },
                }
        if src:
            # 幂等：本文件已有则跳过
            if note_id not in existing_ids:
                new_notes.append(RawNote.from_json(src))
                existing_ids.add(note_id)
            pending_store.update_pending(note_id, "resolved", events_dir)
            resolved += 1
        else:
            no_content += 1  # 保持 pending

    # 追加写入（不覆盖 router 已写入的 note_view）
    if new_notes:
        merged = []
        if out_path.exists():
            for ln in out_path.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    merged.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
        seen = {m["note_id"] for m in merged}
        for r in new_notes:
            if r.note_id not in seen:
                merged.append(r.to_dict())
        with open(out_path, "w", encoding="utf-8") as f:
            for m in merged:
                f.write(json.dumps(m, ensure_ascii=False) + "\n")

    still = pending_store.pending_count(events_dir)
    return {"resolved": resolved, "still_pending": still, "no_content": no_content}
