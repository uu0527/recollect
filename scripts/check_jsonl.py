#!/usr/bin/env python3
"""
JSONL 质量检查（真实采集数据验收）

用法：
    python scripts/check_jsonl.py <path.jsonl>

统计：
- 总条数
- 各字段非空率（note_id/title/url/author/content/images）
- 空壳比例（只有 note_id/url，无正文/图片等有效内容）
- 有效性判断（有效率 >= 80% 才算通过）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def check(path: str) -> int:
    p = Path(path)
    if not p.exists():
        print(f"[ERROR] 文件不存在: {path}")
        return 2

    notes = []
    with open(p, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                notes.append(json.loads(ln))
            except json.JSONDecodeError as e:
                print(f"[WARN] 第 {len(notes)+1} 行 JSON 解析失败: {e}")

    total = len(notes)
    if total == 0:
        print("[ERROR] 文件为空或无可解析记录")
        return 3

    print("=" * 50)
    print(f"文件: {p.name} | 大小: {p.stat().st_size} bytes")
    print("=" * 50)

    # 1. 字段非空率
    fields = ["note_id", "url", "title", "content", "images", "metadata"]
    print("\n-- 字段非空率 --")
    field_stats = {}
    for fld in fields:
        nonempty = 0
        for n in notes:
            v = n.get(fld)
            if fld == "images":
                if isinstance(v, list) and len(v) > 0:
                    nonempty += 1
            elif fld == "metadata":
                if isinstance(v, dict) and len(v) > 0:
                    nonempty += 1
            elif v not in (None, ""):
                nonempty += 1
        rate = nonempty / total * 100 if total else 0
        field_stats[fld] = (nonempty, rate)
        print(f"  {fld:<10} {nonempty:>4}/{total} ({rate:.1f}%)")

    # 2. 空壳判定
    print("\n-- 空壳分析 --")
    shells = []
    valid = []
    for n in notes:
        has_content = bool((n.get("content") or "").strip())
        has_images = isinstance(n.get("images"), list) and len(n["images"]) > 0
        title_raw = (n.get("title") or "").strip()
        # 占位标题（[ReCollect] URL 形式）不算有效标题
        has_title = bool(title_raw) and not title_raw.startswith("[ReCollect]")
        # 空壳：无正文且无图片且无有效标题（只有 note_id/url）
        if not has_content and not has_images and not has_title:
            shells.append(n)
        else:
            valid.append(n)

    shell_rate = len(shells) / total * 100 if total else 0
    success_rate = len(valid) / total * 100 if total else 0
    print(f"  总数据:   {total}")
    print(f"  有效数据: {len(valid)}（有正文/图片/标题任一）")
    print(f"  空壳:     {len(shells)}（仅 note_id/url）")
    print(f"  有效率:   {success_rate:.1f}%")

    # 3. 空壳明细
    if shells:
        print("\n-- 空壳记录 --")
        for n in shells:
            print(f"  {n.get('note_id','?')} | {str(n.get('url',''))[:60]}")

    # 4. 结论
    print("\n" + "=" * 50)
    if success_rate >= 80:
        print(f"结论: 有效率 {success_rate:.1f}% >= 80% → 达到真实链路门槛 ✅")
        return 0
    else:
        print(f"结论: 有效率 {success_rate:.1f}% < 80% → 未达门槛，需排查采集问题")
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python scripts/check_jsonl.py <path.jsonl>")
        sys.exit(2)
    sys.exit(check(sys.argv[1]))
