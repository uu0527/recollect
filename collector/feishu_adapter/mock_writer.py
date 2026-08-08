"""
Mock Feishu Writer Adapter（仅模拟，不调用真实飞书 API）

职责：
  读取 P4 写入记录 data/04_write/{task}_write_records.jsonl，
  结合 P3 summary（data/03_summary/{task}_summary.json）作为内容源，
  生成模拟飞书多维表行 → data/04_write/mock_feishu_bitable.jsonl。

模拟飞书表结构：
  {title, category, tags, summary, source_url, created_at}

原则：
  - 不调用真实飞书 API（无认证/无网络）
  - 不修改现有 pipeline
  - 只处理 write_success=true 的记录（模拟表里只有成功写入的行）
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT_FILE_NAME = "mock_feishu_bitable.jsonl"


# ============================================================
# 读取
# ============================================================
def load_write_records(write_dir: Path, task_id: str) -> List[Dict]:
    """读取 {task}_write_records.jsonl"""
    p = write_dir / f"{task_id}_write_records.jsonl"
    records = []
    if p.exists():
        for ln in p.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                records.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return records


def load_summary(summary_dir: Path, task_id: str) -> Dict[str, Dict]:
    """读取 {task}_summary.json（list of SummarizedNote）→ note_id → dict"""
    p = summary_dir / f"{task_id}_summary.json"
    result: Dict[str, Dict] = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return result
        items = data if isinstance(data, list) else [data]
        for it in items:
            if it.get("note_id"):
                result[it["note_id"]] = it
    return result


# ============================================================
# 转换
# ============================================================
def to_bitable_row(record: Dict, summary: Dict) -> Dict:
    """write_record + summary → 模拟飞书表行"""
    note_id = record.get("note_id", "")
    s = summary.get(note_id, {})
    return {
        "title": s.get("title", ""),
        "category": s.get("category_l1", "") or s.get("category_l2", ""),
        "tags": s.get("tags", []),
        "summary": s.get("tldr", ""),
        "source_url": s.get("url", ""),
        "created_at": record.get("write_time", datetime.now().isoformat(timespec="seconds")),
    }


def build_mock_bitable(write_dir: Path, summary_dir: Path, task_id: str) -> List[Dict]:
    """主流程：读记录 + 对照 summary → 生成表行（仅 write_success=true）"""
    records = load_write_records(write_dir, task_id)
    summaries = load_summary(summary_dir, task_id)

    rows = []
    skipped = 0
    for rec in records:
        if not rec.get("write_success"):
            skipped += 1
            continue  # 只模拟成功写入的行
        rows.append(to_bitable_row(rec, summaries))

    # 输出
    out_path = write_dir / OUT_FILE_NAME
    with open(out_path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"[mock-feishu] 生成 {len(rows)} 行 → {out_path.name}（跳过 {skipped} 条非成功记录）")
    return rows


# ============================================================
# 入口
# ============================================================
def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Mock Feishu Writer Adapter")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--write-dir", default=str(ROOT / "data" / "04_write"))
    ap.add_argument("--summary-dir", default=str(ROOT / "data" / "03_summary"))
    args = ap.parse_args()

    rows = build_mock_bitable(Path(args.write_dir), Path(args.summary_dir), args.task_id)
    for i, r in enumerate(rows, 1):
        print(f"  [{i}] {r['title'][:24]} | {r['category']} | tags={len(r['tags'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
