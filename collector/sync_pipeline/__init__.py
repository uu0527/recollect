"""
Sync Pipeline（Phase 2）— 自动触发全链路

职责：
  sync_once():
  1. 读取 data/events/*.jsonl
  2. event_router 分流（note_view → RawNote；note_collect → pending）
  3. content_resolver 解析 pending → RawNote
  4. 若 data/01_raw 有新增 → 自动跑 P2→P3→P5→P4→P6（真实 LLM）

用法：
  python -m collector.sync_pipeline
  （--task-id 指定；默认用当天日期）

不修改任何已有 pipeline 模块。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.event_router import route_events  # noqa: E402
from collector.content_resolver import resolve_pending  # noqa: E402


def sync_once(events_dir: Path, out_dir: Path, run_pipeline: bool = True,
              task_id: str | None = None, **pipeline_kwargs) -> dict:
    """执行一次完整同步：路由 → 解析 → 触发 pipeline"""
    print("=" * 56)
    print("ReCollect Sync Pipeline (Phase 2)")
    print("=" * 56)

    # 1) 路由事件
    print(f"\n[1/3] 路由事件 ← {events_dir}")
    stats = route_events(events_dir, out_dir)
    print(f"  note_view 新增: {stats['view_added']} | 跳过: {stats['view_skipped']}")
    print(f"  note_collect 新增 pending: {stats['collect_new']} | 重复: {stats['collect_dup']}")
    print(f"  其他跳过: {stats['skipped']}")

    # 2) 解析 pending
    print(f"\n[2/3] 解析 pending task")
    r = resolve_pending(events_dir, out_dir)
    print(f"  resolved: {r['resolved']} | 仍 pending: {r['still_pending']} | 无内容: {r['no_content']}")

    # 3) 触发 pipeline
    tid = task_id or f"events_{datetime.now().strftime('%Y%m%d')}"
    if not run_pipeline:
        print(f"\n[3/3] (跳过 pipeline，--no-pipeline)")
        print("=" * 56)
        return {**stats, **r, "pipeline": "skipped", "task_id": tid}

    # 检查是否有新 RawNote（router 输出 events_{date}.jsonl）
    from datetime import datetime as _dt
    date_str = _dt.now().strftime("%Y%m%d")
    raw_file = out_dir / f"events_{date_str}.jsonl"
    n = 0
    if raw_file.exists():
        n = sum(1 for _ in raw_file.read_text(encoding="utf-8").splitlines() if _.strip())

    if n == 0 and r["still_pending"] == 0 and stats["view_added"] == 0:
        print(f"\n[3/3] 无新增数据，跳过 pipeline")
        print("=" * 56)
        return {**stats, **r, "pipeline": "no_data", "task_id": tid}

    # 对齐文件名：router 输出 events_{date}.jsonl → pipeline 需要 {task_id}_notes.jsonl
    if raw_file.exists():
        target = out_dir / f"{tid}_notes.jsonl"
        if raw_file.resolve() != target.resolve():
            import shutil
            shutil.copy(raw_file, target)
        print(f"  输入文件对齐: {raw_file.name} → {target.name}")

    print(f"\n[3/3] 触发 pipeline (task_id={tid})")
    _run_p2_p6(tid, **pipeline_kwargs)
    print("=" * 56)
    return {**stats, **r, "pipeline": "run", "task_id": tid}


def _run_p2_p6(task_id: str, skip_multimodal: bool = False) -> None:
    """按顺序跑 P2 → P3 → P5 → P4 → P6（真实 LLM）"""
    from pipeline.p2_screen import run as p2
    from pipeline.p3_summary import run as p3
    from pipeline.p5_audit import run as p5
    from pipeline.p4_write import run as p4
    from pipeline.p6_memory import run as p6

    print(f"--- P2 筛选 ---")
    p2(task_id)
    print(f"--- P3 归纳 ---")
    p3(task_id, skip_multimodal=skip_multimodal)
    print(f"--- P5 审计 ---")
    p5(task_id)
    print(f"--- P4 飞书写入 ---")
    p4(task_id, use_mock=False)
    print(f"--- P6 索引 ---")
    p6(task_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="ReCollect Sync Pipeline")
    ap.add_argument("--events-dir", default=str(ROOT / "data" / "events"))
    ap.add_argument("--out", default=str(ROOT / "data" / "01_raw"))
    ap.add_argument("--task-id", default=None)
    ap.add_argument("--no-pipeline", action="store_true", help="只做路由+解析，不跑 LLM")
    ap.add_argument("--skip-multimodal", action="store_true")
    args = ap.parse_args()

    sync_once(
        Path(args.events_dir), Path(args.out),
        run_pipeline=not args.no_pipeline,
        task_id=args.task_id,
        skip_multimodal=args.skip_multimodal,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
