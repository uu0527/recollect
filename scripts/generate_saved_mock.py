"""
Generate frontend saved_mock.json from real Supabase events data.

背景（Phase 3.5 regression fix）:
  ae6fbe7 重建 knowledge_mock.json 后，knowledge 的 source_saved_ids 用真实 note_id，
  但 saved_mock.json 仍是旧虚构 note_id → 交集为 0 → Knowledge 列表被 isKnowledgeVisible 全部过滤
  → 帖子内容消失 / Ask Agent 无法跳转。

修复:
  从 Supabase events 表（note_view）重建 saved_mock.json:
  - note_id = 真实 events.note_id（与 knowledge.source_saved_ids 完全对应）
  - title/content/author/images/url 直接取 events 字段
  - status = "Knowledge Ready"（与已有 knowledge 对齐）
  - env = "prod"

用法:
  python scripts/generate_saved_mock.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_FILE = ROOT / "frontend" / "data" / "saved_mock.json"


def load_real_events() -> list:
    """从 Supabase events 拉取 note_view 事件（真实 saved 数据源）"""
    import os
    import config  # noqa: F401  # 加载 .env
    from supabase import create_client

    client = create_client(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", ""))
    resp = client.table("events").select("*").order("created_at", desc=True).limit(100).execute()
    rows = resp.data or []
    return [e for e in rows if e.get("event_type") in ("note_view", "")]


def to_saved_item(ev: dict) -> dict:
    """Supabase events 行 → 前端 saved_mock 条目"""
    note_id = ev.get("note_id", "")
    url = ev.get("url") or f"https://www.xiaohongshu.com/explore/{note_id}"
    return {
        "note_id": note_id,
        "title": ev.get("title", "") or "未命名收藏",
        "source": url,
        "collected_at": (ev.get("created_at") or "")[:19],
        "author": ev.get("author", "") or "未知",
        "content": ev.get("content", "") or (ev.get("title", "") or ""),
        "images": ev.get("images") or [],
        "status": "Knowledge Ready",  # 已有 knowledge → 状态对齐
        "env": "prod",
    }


def main() -> None:
    events = load_real_events()
    if not events:
        print("[ERROR] Supabase events 无数据")
        sys.exit(1)
    items = [to_saved_item(ev) for ev in events]
    payload = {
        "generated_at": "realtime",
        "source": "supabase events(note_view)",
        "note": "saved items from Supabase events，note_id 与 knowledge.source_saved_ids 一致",
        "items": items,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已重建: {OUT_FILE}")
    print(f"saved 条目: {len(items)}")
    for it in items[:5]:
        print(f"  {it['note_id'][:14]} | {it['title'][:24]} | {it['status']}")


if __name__ == "__main__":
    main()
