"""
Regression Test: Knowledge Detail → Ask Agent flow（Phase 3.5 bug fix）

背景 bug:
  前端 Knowledge Detail → Ask Agent 传 knowledge_id="kn_001"（虚构 id），
  后端 Supabase knowledge 表按 note_id 标识 → 解析失败 → Context Injection 失败。

修复验证:
  1. frontend/data/knowledge_mock.json 中 knowledge_id = 真实 note_id
  2. 每条 mock note_id 可被后端 get_knowledge_by_note_id 解析
  3. AgentOrchestrator._resolve_context 用 mock note_id 能成功解析

用法:
  python tests/test_ask_agent_flow.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MOCK_FILE = ROOT / "frontend" / "data" / "knowledge_mock.json"

PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def main() -> None:
    print("=== Regression: Knowledge Detail → Ask Agent flow ===\n")

    # 1. mock 结构验证
    print("[1] mock knowledge_id = 真实 note_id")
    data = json.loads(MOCK_FILE.read_text(encoding="utf-8"))
    items = data["items"]
    check("mock 非空", len(items) > 0, f"(items={len(items)})")
    for it in items[:5]:
        kid = it.get("knowledge_id", "")
        note_id = it.get("note_id", "")
        check(
            f"knowledge_id 是真实 note_id: {kid[:14]}",
            bool(kid) and (not kid.startswith("kn_")),
            f"(kid={kid})",
        )
        check(
            f"note_id 字段存在且一致: {note_id[:14]}",
            bool(note_id) and note_id == kid,
            f"(note_id={note_id}, knowledge_id={kid})",
        )

    # 2. 后端解析验证（Supabase）
    print("\n[2] mock note_id 可被后端解析")
    from backend.agent.orchestrator import AgentOrchestrator

    orch = AgentOrchestrator()
    from collector.context_store.adapters import get_adapter

    adapter = get_adapter()
    resolvable = 0
    for it in items:
        note_id = it.get("note_id") or it.get("knowledge_id")
        if not note_id:
            continue
        card = adapter.get_knowledge_by_note_id(note_id)
        if card:
            resolvable += 1
        else:
            check(f"  note_id 可解析: {note_id[:14]}", False, "(Supabase 无此 note_id)")
    check(
        f"全部 note_id 可被 get_knowledge_by_note_id 解析",
        resolvable == len(items),
        f"({resolvable}/{len(items)})",
    )

    # 3. Orchestrator 集成验证
    print("\n[3] _resolve_context 用 mock note_id 能成功解析")
    first = items[0]
    note_id = first.get("note_id") or first.get("knowledge_id")
    assets = orch._resolve_context({"knowledge_id": note_id}, "总结这个知识")
    check(
        "related query → 成功解析 asset",
        len(assets) == 1,
        f"(assets={len(assets)})",
    )
    check(
        "asset 是真实 knowledge",
        bool(assets) and assets[0].get("note_id") == note_id,
    )
    check(
        "router 决策 = inject",
        bool(getattr(orch, "_last_router_decision", None))
        and orch._last_router_decision.should_inject,
        f"(decision={getattr(orch._last_router_decision, 'should_inject', None)})",
    )

    # 4. 旧虚构 id 不再传递（bug 回归）
    print("\n[4] mock 无虚构 kn_ id")
    fake = [it for it in items if it.get("knowledge_id", "").startswith("kn_")]
    check("无 kn_ 虚构 id", not fake, f"(found={len(fake)})")

    # 5. 解析失败日志增强验证
    print("\n[5] 解析失败时记录 context_error")
    assets_bad = orch._resolve_context({"knowledge_id": "not_exist_id"}, "测试")
    check("不存在 id → 空 asset", assets_bad == [])
    check(
        "记录 _last_context_error",
        bool(getattr(orch, "_last_context_error", None)),
        f"(error={getattr(orch, '_last_context_error', None)})",
    )

    print(f"\n=== 结果: {PASS} 通过 / {FAIL} 失败 ===")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
