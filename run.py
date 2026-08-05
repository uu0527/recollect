"""
ReCollect - 统一 CLI Harness 入口
Phase 1: 仅参数解析 + 阶段调度框架，无业务逻辑

Usage:
    python run.py --task_id demo01 --stage all
    python run.py --task_id demo01 --stage p2
    python run.py --task_id demo01 --stage p6 --query "xxx"
    python run.py --task_id demo01 --dry_run
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许直接运行：python run.py
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import click
from config import STAGE_ORDER

VALID_STAGES = {"all", *STAGE_ORDER}


# ============================================================
# 阶段调度（Phase 2：透传 CLI 参数）
# ============================================================
def _dispatch_stage(stage: str, task_id: str, ctx: click.Context) -> None:
    """按阶段名派发到对应模块，透传 click ctx 参数"""
    opts = ctx.params
    model_override = opts.get("model_override")
    skip_multimodal = bool(opts.get("skip_multimodal"))
    q = opts.get("query")

    click.echo(f"[Harness] stage={stage}  task_id={task_id}")

    if stage == "p1":
        from pipeline.p1_collect import run as p1_run
        p1_run(task_id=task_id, model_override=model_override)
    elif stage == "p2":
        from pipeline.p2_screen import run as p2_run
        p2_run(task_id=task_id, model_override=model_override)
    elif stage == "p3":
        from pipeline.p3_summary import run as p3_run
        p3_run(task_id=task_id, model_override=model_override,
               skip_multimodal=skip_multimodal)
    elif stage == "p5":
        from pipeline.p5_audit import run as p5_run
        p5_run(task_id=task_id, model_override=model_override)
    elif stage == "p4":
        from pipeline.p4_write import run as p4_run
        p4_run(task_id=task_id, model_override=model_override)
    elif stage == "p6":
        from pipeline.p6_memory import run as p6_run
        from pipeline.p6_memory import query as p6_query
        if q:
            p6_query(task_id=task_id, query_text=q, query_id="cli")
        else:
            p6_run(task_id=task_id, model_override=model_override)
    else:
        raise ValueError(f"Unknown stage: {stage}")


# ============================================================
# CLI 主入口
# ============================================================
@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--task_id", required=True, type=str,
              help="任务 ID，用于幂等重跑 + 输出文件名前缀")
@click.option("--stage", "stages",
              type=click.Choice(sorted(VALID_STAGES)),
              default="all", show_default=True,
              help="运行阶段：all=全链路，或 p1/p2/p3/p5/p4/p6 单阶段")
@click.option("--model_override", type=str, default=None,
              help="模型覆写：格式 p3=xxx（预留，Phase 2 生效）")
@click.option("--skip_multimodal", is_flag=True, default=False,
              help="P3 跳过图片/视频理解（纯文本降级）")
@click.option("--dry_run", is_flag=True, default=False,
              help="仅打印计划执行的阶段，不实际调用")
@click.option("--query", type=str, default=None,
              help="P6 单问模式直接传入查询文本")
def main(task_id: str, stages: str, model_override: str | None,
         skip_multimodal: bool, dry_run: bool, query: str | None) -> None:
    """ReCollect - 收藏激活助手 统一 Harness 入口"""
    click.echo("=" * 60)
    click.echo(f"  ReCollect (拾遗)  Harness Run")
    click.echo(f"  task_id   = {task_id}")
    click.echo(f"  stage(s)  = {stages}")
    click.echo(f"  dry_run   = {dry_run}")
    click.echo(f"  multi_mod = {not skip_multimodal}")
    click.echo("=" * 60)

    # 1. 展开阶段列表
    if stages == "all":
        stage_list = STAGE_ORDER
    else:
        stage_list = [stages]

    click.echo(f"[Plan] 执行顺序: {' → '.join(stage_list)}")

    if dry_run:
        click.echo("[Dry Run] 仅打印计划，结束。")
        return

    # 2. 阶段调度
    for s in stage_list:
        try:
            _dispatch_stage(s, task_id, click.get_current_context())
        except Exception as e:
            import traceback
            click.echo(f"  ↳ [ERROR] {s} 阶段失败: {e!r}", err=True)
            traceback.print_exc()
            sys.exit(1)

    click.echo("=" * 60)
    click.echo(f"[Done] task_id={task_id}  stages={stages}  执行完成")


if __name__ == "__main__":
    main()
