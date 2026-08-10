"""
Generate frontend knowledge_mock.json from real Supabase knowledge data.

背景（Phase 3.5 bug fix）:
  前端 Ask Agent 传 knowledge_id="kn_001"（虚构），后端 Supabase knowledge 表按 note_id 标识。
  两套 id 脱节 → Context Injection 失败。

修复:
  用 Supabase 真实 knowledge 数据重建 knowledge_mock.json:
  - knowledge_id = 真实 note_id（与后端一致）
  - summary = tldr, concepts = key_points, topic = category_l1
  - source_saved_ids = [note_id]（knowledge 由该 note 生成）

用法:
  python scripts/generate_knowledge_mock.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_FILE = ROOT / "frontend" / "data" / "knowledge_mock.json"


def load_real_knowledge() -> list:
    """从 Supabase 拉取真实 knowledge（过滤测试数据）"""
    import os
    import config  # noqa: F401  # 加载 .env
    from supabase import create_client

    client = create_client(os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", ""))
    resp = client.table("knowledge").select("*").limit(200).execute()
    rows = resp.data or []
    real = []
    for r in rows:
        title = r.get("title", "")
        if "测试" in title or str(r.get("note_id", "")).startswith("n_evt"):
            continue
        if not title.strip():
            continue
        real.append(r)
    return real


def to_mock_item(kn: dict) -> dict:
    """Supabase knowledge 行 → 前端 mock 条目（knowledge_id = note_id）"""
    note_id = kn["note_id"]
    return {
        "knowledge_id": note_id,  # 关键修复: 真实 note_id 而非虚构 id
        "note_id": note_id,  # 显式 note_id（Ask Agent 直接使用）
        "title": kn.get("title", ""),
        "summary": kn.get("tldr", ""),
        "tags": kn.get("tags") or [],
        "topic": kn.get("category_l1", ""),
        "concepts": (kn.get("key_points") or [])[:5],
        "source_saved_ids": [note_id],  # knowledge 由该 note 生成
        "created_at": (kn.get("created_at") or "")[:19],
    }


def main() -> None:
    rows = load_real_knowledge()
    if not rows:
        print("[ERROR] Supabase 无真实 knowledge 数据")
        sys.exit(1)
    items = [to_mock_item(kn) for kn in rows]
    payload = {
        "generated_at": "realtime",
        "note": "knowledge assets from Supabase knowledge 表（knowledge_id = 真实 note_id，与后端一致）",
        "items": items,
    }
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"已重建: {OUT_FILE}")
    print(f"knowledge 条目: {len(items)}")
    for it in items[:5]:
        print(f"  {it['knowledge_id'][:14]} | {it['title'][:24]}")


if __name__ == "__main__":
    main()
