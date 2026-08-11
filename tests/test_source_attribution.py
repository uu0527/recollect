"""
Regression Test: Source Attribution（explicit context source）

背景 bug:
  context_applied=true（Context Injection 成功），但 API response sources=[]。
  根因: sources 只来自 Retriever，explicit context 解析的 Knowledge Asset 未合并。

修复验证:
  Case A: Explicit context + router inject → sources 含指定 note_id（title/url/tldr 正确）
  Case B: Explicit context + router skip  → 不伪造 source，保持普通 Chat
  Case C: 普通 Chat（无 context）          → Retriever source 行为不变
  Case D: Invalid note_id                 → context_applied=false，不伪造 source
  Case E: Retriever + Explicit 同时存在    → sources 去重，explicit 优先

用法:
  python tests/test_source_attribution.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.orchestrator import AgentOrchestrator  # noqa: E402

PASS = 0
FAIL = 0

# 真实 Supabase 数据（测试用，若 Supabase 不可用则回退 mock 单测）
REAL_NOTE_ID = "69058a8e000000000501005a"  # 话梅知识


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        print(f"  ✗ {name} {detail}")


def main() -> None:
    print("=== Regression: Source Attribution ===\n")
    orch = AgentOrchestrator()

    # ---- Case A: Explicit context + router inject ----
    print("[Case A] Explicit context + inject → sources 非空")
    res = orch.handle(query="总结这个知识", session_id="sa_a", context={"knowledge_id": REAL_NOTE_ID})
    md = res["metadata"]
    sources = res["sources"]
    check("context_applied=true", md.get("context_applied") is True, f"({md.get('context_applied')})")
    check("router.should_inject=true", md.get("router", {}).get("should_inject") is True)
    check("sources 非空", len(sources) > 0, f"(sources={len(sources)})")
    check(
        "sources 含指定 note_id",
        any(s.get("note_id") == REAL_NOTE_ID for s in sources),
        f"(sources ids={[s.get('note_id') for s in sources]})",
    )
    src = next((s for s in sources if s.get("note_id") == REAL_NOTE_ID), None)
    check("source.title 非空", bool(src and src.get("title")), f"({src and src.get('title')})")
    check("source.url 非空", bool(src and src.get("url")), f"({src and src.get('url')})")
    check("source.tldr 非空", bool(src and src.get("tldr")), f"({src and src.get('tldr')})")

    # ---- Case B: Explicit context + router skip ----
    print("\n[Case B] Explicit context + router skip → 不伪造 source")
    res_b = orch.handle(query="如何优化 React 组件性能", session_id="sa_b", context={"knowledge_id": REAL_NOTE_ID})
    md_b = res_b["metadata"]
    check("context_applied=false", md_b.get("context_applied") is False, f"({md_b.get('context_applied')})")
    check(
        "sources 不含该 context note_id（未注入不 attribution）",
        not any(s.get("note_id") == REAL_NOTE_ID for s in res_b["sources"]),
        f"(sources={[s.get('note_id') for s in res_b['sources']]})",
    )

    # ---- Case C: 普通 Chat（无 context）----
    print("\n[Case C] 普通 Chat（无 context）")
    res_c = orch.handle(query="介绍一下猫寿命研究", session_id="sa_c")
    check("无 context 不报错", res_c["answer"] != "")
    # Retriever 可能命中（query 含实体词）也可能不命中，只验证结构完整
    for s in res_c["sources"]:
        check("source schema 完整", all(k in s for k in ("note_id", "title", "url", "category_l1", "tldr")))

    # ---- Case D: Invalid note_id ----
    print("\n[Case D] Invalid note_id")
    res_d = orch.handle(query="总结这个知识", session_id="sa_d", context={"knowledge_id": "not_exist_xyz"})
    md_d = res_d["metadata"]
    check("context_applied=false", md_d.get("context_applied") is False, f"({md_d.get('context_applied')})")
    check(
        "不伪造 source（无 not_exist）",
        not any("not_exist" in s.get("note_id", "") for s in res_d["sources"]),
    )
    check("API 正常返回", res_d["answer"] != "")

    # ---- Case E: 去重（单测合并函数）----
    print("\n[Case E] Retriever + Explicit 去重")
    ctx_assets = [{"note_id": "n1", "title": "T", "url": "U", "category_l1": "C", "tldr": "D"}]
    retriever_src = [
        {"note_id": "n1", "title": "T", "url": "U", "category_l1": "C", "tldr": "D"},
        {"note_id": "n2", "title": "T2", "url": "U2", "category_l1": "C2", "tldr": "D2"},
    ]
    merged = AgentOrchestrator._merge_explicit_context_source(retriever_src, ctx_assets)
    check("去重后 n1 只出现一次", [s["note_id"] for s in merged].count("n1") == 1)
    check("explicit 优先（n1 在前）", merged[0]["note_id"] == "n1")
    check("retriever 其他 source 保留", "n2" in [s["note_id"] for s in merged])

    print(f"\n=== 结果: {PASS} 通过 / {FAIL} 失败 ===")
    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    main()
