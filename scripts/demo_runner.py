"""
直接脚本方式运行：demo01 全链路
（不依赖 click，用于当前环境 alias 验证时的兜底）
使用：
    cd recollect
    python -c "import scripts.demo_runner; scripts.demo_runner.run_all('demo01')"
或直接：
    python scripts/demo_runner.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.p1_collect import run as p1
from pipeline.p2_screen import run as p2
from pipeline.p3_summary import run as p3
from pipeline.p5_audit import run as p5
from pipeline.p4_write import run as p4
from pipeline.p6_memory import run as p6


def run_all(task_id: str = "demo01"):
    sep = "=" * 60
    print(sep)
    print(f"  ReCollect E2E Demo Run   task_id={task_id}")
    print(sep)
    print(f"[1/6] P1 采集")
    p1(task_id=task_id)
    print()
    print(f"[2/6] P2 筛选")
    p2(task_id=task_id)
    print()
    print(f"[3/6] P3 归纳")
    p3(task_id=task_id)
    print()
    print(f"[4/6] P5 审计（先于P4）")
    p5(task_id=task_id)
    print()
    print(f"[5/6] P4 飞书写入（mock）→ 同时触发 P6 增量索引")
    p4(task_id=task_id)
    print()
    print(f"[6/6] P6 检索问答")
    p6(task_id=task_id)
    print()
    print(sep)
    print(f"✅ 全链路完成 task_id={task_id}")
    print(sep)
    return task_id


if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else "demo01"
    run_all(tid)
