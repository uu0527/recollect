#!/usr/bin/env python3
"""
Browser Event Collector - Local Agent 侧事件摄入

功能：
  读取 data/events/*.jsonl（Chrome 插件导出的事件流）
  → 过滤 note_view 事件
  → note_id 幂等去重（已存在 data/01_raw 的不重复写入）
  → 转换为 RawNote schema
  → 追加写入 data/01_raw/events_{date}.jsonl

用法：
  python -m collector.context_store.event_ingest
  （或带参数）python -m collector.context_store.event_ingest --events-dir data/events --out data/01_raw

不修改 P2-P6。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from schemas import RawNote, dump_jsonl  # noqa: E402


def read_events(events_dir: Path) -> List[Dict]:
    """读取 data/events/*.jsonl，返回事件列表"""
    events = []
    if not events_dir.exists():
        print(f"[ingest] 事件目录不存在: {events_dir}")
        return events
    for f in sorted(events_dir.glob("*.jsonl")):
        try:
            with open(f, encoding="utf-8") as fh:
                for ln in fh:
                    ln = ln.strip()
                    if not ln:
                        continue
                    try:
                        events.append(json.loads(ln))
                    except json.JSONDecodeError as e:
                        print(f"[ingest] 跳过坏行 {f.name}: {e}")
        except OSError as e:
            print(f"[ingest] 读取失败 {f.name}: {e}")
    return events


def event_to_raw(event: Dict) -> RawNote | None:
    """事件 → RawNote。仅接受 note_view 且有正文的事件"""
    if event.get("event_type") != "note_view":
        return None
    note_id = event.get("note_id", "")
    content = event.get("content", "")
    if not note_id or not content:
        return None
    return RawNote(
        note_id=note_id,
        url=event.get("url", ""),
        title=event.get("title", ""),
        content=content,
        images=event.get("images", []) or [],
        metadata={
            "source": "browser_event",
            "author": event.get("author", ""),
            "event_timestamp": event.get("timestamp", ""),  # 保留事件时间
            "event_type": event.get("event_type", "note_view"),
        },
    )


def load_existing_ids(out_path: Path) -> set:
    """读取输出文件已有 note_id（幂等）"""
    ids = set()
    if not out_path.exists():
        return ids
    for ln in out_path.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            ids.add(json.loads(ln)["note_id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return ids


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--events-dir", default=str(ROOT / "data" / "events"), help="事件目录（插件导出）")
    ap.add_argument("--out", default=str(ROOT / "data" / "01_raw"), help="输出目录（RawNote JSONL）")
    args = ap.parse_args()

    events_dir = Path(args.events_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    events = read_events(events_dir)
    if not events:
        print("[ingest] 无事件文件，退出")
        return 0
    print(f"[ingest] 读取事件 {len(events)} 条")

    # 过滤 + 转换
    raws = []
    skipped_no_content = 0
    for ev in events:
        raw = event_to_raw(ev)
        if raw is None:
            skipped_no_content += 1
            continue
        raws.append(raw)
    print(f"[ingest] 可转换 note_view 事件 {len(raws)} 条（跳过非 view/无正文 {skipped_no_content} 条）")

    if not raws:
        return 0

    # 幂等去重（同批次 + 文件已有均过滤）
    today = datetime.now().strftime("%Y%m%d")
    out_path = out_dir / f"events_{today}.jsonl"
    seen: set = load_existing_ids(out_path)
    new_notes = []
    for r in raws:
        if r.note_id in seen:
            continue
        seen.add(r.note_id)
        new_notes.append(r)
    print(f"[ingest] 去重后新增 {len(new_notes)} 条（重复 {len(raws) - len(new_notes)} 条）")

    if new_notes:
        dump_jsonl(str(out_path), new_notes)
        print(f"[ingest] ✅ 写入 {len(new_notes)} 条 → {out_path}")
    else:
        print("[ingest] 无新增（全部重复）")

    print(f"[ingest] 完成。P2-P6 可直接消费 {out_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
