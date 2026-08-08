"""
Sync Pipeline（Phase 2）— 自动触发全链路

职责：
  sync_once():
  1. 读取 data/events/*.jsonl
  2. event_router 分流（note_view → RawNote；note_collect → pending）
  3. content_resolver 解析 pending → RawNote
  4. 若 data/01_raw 有新增 → 自动跑 P2→P3→P5→P4→P6（真实 LLM）
  5. 每次执行后追加一条 Pipeline Run Audit 记录
     （data/05_audit/pipeline_runs.jsonl）

用法：
  python -m collector.sync_pipeline
  （--task-id 指定；默认用当天日期）

不修改任何已有 pipeline 模块。
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.event_router import route_events  # noqa: E402
from collector.content_resolver import resolve_pending  # noqa: E402

AUDIT_FILE = ROOT / "data" / "05_audit" / "pipeline_runs.jsonl"


# ============================================================
# Pipeline Run Audit
# ============================================================
def _append_audit(record: dict) -> None:
    """追加一条 pipeline run 审计记录（标准 jsonl 追加写入）"""
    AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _count_lines(path: Path) -> int:
    """统计 jsonl 文件行数（不存在返回 0）"""
    if not path.exists():
        return 0
    try:
        return sum(1 for _ in path.read_text(encoding="utf-8").splitlines() if _.strip())
    except OSError:
        return 0


def sync_once(events_dir: Path, out_dir: Path, run_pipeline: bool = True,
              task_id: str | None = None, **pipeline_kwargs) -> dict:
    """执行一次完整同步：路由 → 解析 → 触发 pipeline → 写 audit"""
    started_at = datetime.now().isoformat(timespec="seconds")
    print("=" * 56)
    print("ReCollect Sync Pipeline (Phase 2)")
    print("=" * 56)

    tid = task_id or f"events_{datetime.now().strftime('%Y%m%d')}"

    try:
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
        if not run_pipeline:
            print(f"\n[3/3] (跳过 pipeline，--no-pipeline)")
            print("=" * 56)
            _append_audit({
                "task_id": tid,
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "status": "skipped",
                "stages": {"route": "success", "resolve": "success"},
                "stats": {
                    "note_view": stats["view_added"],
                    "note_collect": stats["collect_new"],
                    "resolved": r["resolved"],
                    "screened": 0,
                    "written": 0,
                },
            })
            return {**stats, **r, "pipeline": "skipped", "task_id": tid}

        # 检查是否有新 RawNote（router 输出 events_{date}.jsonl）
        from datetime import datetime as _dt
        date_str = _dt.now().strftime("%Y%m%d")
        raw_file = out_dir / f"events_{date_str}.jsonl"
        n = _count_lines(raw_file)

        if n == 0 and r["still_pending"] == 0 and stats["view_added"] == 0:
            print(f"\n[3/3] 无新增数据，跳过 pipeline")
            print("=" * 56)
            _append_audit({
                "task_id": tid,
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "status": "no_data",
                "stages": {"route": "success", "resolve": "success"},
                "stats": {
                    "note_view": stats["view_added"],
                    "note_collect": stats["collect_new"],
                    "resolved": r["resolved"],
                    "screened": 0,
                    "written": 0,
                },
            })
            return {**stats, **r, "pipeline": "no_data", "task_id": tid}

        # 对齐文件名：router 输出 events_{date}.jsonl → pipeline 需要 {task_id}_notes.jsonl
        if raw_file.exists():
            target = out_dir / f"{tid}_notes.jsonl"
            if raw_file.resolve() != target.resolve():
                import shutil
                shutil.copy(raw_file, target)
            print(f"  输入文件对齐: {raw_file.name} → {target.name}")

        print(f"\n[3/3] 触发 pipeline (task_id={tid})")
        stage_stats = _run_p2_p6(tid, **pipeline_kwargs)
        print("=" * 56)

        # 审计：completed
        _append_audit({
            "task_id": tid,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "completed",
            "stages": stage_stats["stages"],
            "stats": {
                "note_view": stats["view_added"],
                "note_collect": stats["collect_new"],
                "resolved": r["resolved"],
                "screened": stage_stats["stats"].get("screened", 0),
                "written": stage_stats["stats"].get("written", 0),
            },
        })
        return {**stats, **r, "pipeline": "run", "task_id": tid}

    except Exception as e:
        # 审计：failed（记录失败阶段 + 错误信息），然后继续抛出原异常
        failed_stage = getattr(e, "_rc_stage", None) or "unknown"
        _append_audit({
            "task_id": tid,
            "started_at": started_at,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": "failed",
            "failed_stage": failed_stage,
            "error": f"{type(e).__name__}: {e}",
        })
        raise


class _StageError(Exception):
    """标记失败阶段的异常包装（透传原异常信息）"""

    def __init__(self, stage: str, original: Exception):
        super().__init__(str(original))
        self._rc_stage = stage
        self._original = original


def _run_p2_p6(task_id: str, skip_multimodal: bool = False) -> dict:
    """按顺序跑 P2 → P3 → P5 → P4 → P6（真实 LLM）
    逐阶段记录 stages 状态；某阶段失败 → 抛出 _StageError（标记阶段），
    由 sync_once 捕获写 audit 后 re-raise（不改变原异常行为）"""
    from pipeline.p2_screen import run as p2
    from pipeline.p3_summary import run as p3
    from pipeline.p5_audit import run as p5
    from pipeline.p4_write import run as p4
    from pipeline.p6_memory import run as p6

    stages: dict = {}
    stats: dict = {"screened": 0, "written": 0}

    def _stage(name, fn):
        print(f"--- {name} ---")
        try:
            out = fn()
            stages[name] = "success"
            return out
        except Exception as e:
            stages[name] = "failed"
            raise _StageError(name, e) from e

    # P2 筛选（返回 screened 文件路径 → 行数 = screened 条数）
    out2 = _stage("p2_screen", lambda: p2(task_id))
    if out2:
        stats["screened"] = _count_lines(Path(out2))

    # P3 归纳
    _stage("p3_summary", lambda: p3(task_id, skip_multimodal=skip_multimodal))

    # P5 审计
    _stage("p5_audit", lambda: p5(task_id))

    # P4 飞书写入（返回 write records 路径 → 行数 = written 条数）
    out4 = _stage("p4_write", lambda: p4(task_id, use_mock=False))
    if out4:
        stats["written"] = _count_lines(Path(out4))

    # P6 索引
    _stage("p6_memory", lambda: p6(task_id))

    return {"stages": stages, "stats": stats}


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
