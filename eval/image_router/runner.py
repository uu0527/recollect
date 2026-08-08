"""
Image Router Eval Runner

用法：
  python eval/image_router/runner.py            # 跑全部 case
  python eval/image_router/runner.py --case xiaohongshu_summer_outfit  # 单个 case

输出：控制台报告 + eval/image_router/results.json（结构化结果）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.image_router import select_images  # noqa: E402
from eval.image_router.metrics import (  # noqa: E402
    image_reduction_rate,
    information_preservation,
    token_saving_estimate,
)

EVAL_DIR = Path(__file__).resolve().parent
CASES_FILE = EVAL_DIR / "cases.json"
RESULTS_FILE = EVAL_DIR / "results.json"

# 真实笔记数据目录
RAW_DIR = ROOT / "data" / "01_raw"


# ============================================================
# Case 数据加载
# ============================================================
def load_cases() -> List[Dict]:
    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    return data["cases"]


def load_real_images(note_id: str) -> List[str]:
    """从 data/01_raw/ 加载真实笔记图片 URL"""
    if not RAW_DIR.exists():
        return []
    for f in sorted(RAW_DIR.glob("*_notes.jsonl")) + sorted(RAW_DIR.glob("events_*.jsonl")):
        try:
            for ln in f.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                d = json.loads(ln)
                if d.get("note_id") == note_id:
                    return [i for i in (d.get("images") or []) if i.startswith("http")]
        except (json.JSONDecodeError, OSError):
            continue
    return []


def synth_images(spec: Dict) -> List[str]:
    """合成测试图片（按 spec 生成 URL + 由 runner 的 metadata_provider 提供尺寸）"""
    urls: List[str] = []
    tall_count = spec.get("tall_count", 0)
    normal_count = spec.get("normal_count", 0)
    dup_of = spec.get("duplicate_of", "")
    dup_count = spec.get("duplicate_count", 0)

    for i in range(tall_count):
        urls.append(f"https://synth.example/tall{i}.webp")
    for i in range(normal_count):
        urls.append(f"https://synth.example/norm{i}.webp")
    if dup_of == "normal" and normal_count:
        dup_url = f"https://synth.example/norm0.webp"
        urls += [dup_url] * dup_count
    if spec.get("cover_small"):
        # 插入小封面（放在最前）
        urls.insert(0, "https://synth.example/cover_small.webp")
    return urls


def synth_metadata_provider(spec: Dict):
    """合成图片的 metadata（长图/普通/封面）"""
    def provider(url: str) -> Dict:
        name = url.split("/")[-1]
        if name.startswith("tall") or name.startswith("knowledge"):
            return {"width": 800, "height": 2000, "size_bytes": 300 * 1024}
        if name.startswith("cover_small"):
            return {"width": 400, "height": 400, "size_bytes": 15 * 1024}
        return {"width": 800, "height": 800, "size_bytes": 100 * 1024}
    return provider


def real_metadata_provider(url: str) -> Dict:
    """真实图片：webp 头解析尺寸（与 P3 的 _select_note_images 一致）"""
    try:
        import struct
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            head = resp.read(40)
            size_hint = resp.headers.get("Content-Length")
        meta: Dict = {}
        if size_hint:
            meta["size_bytes"] = int(size_hint)
        if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
            chunk = head[12:16]
            if chunk == b"VP8X" and len(head) >= 30:
                meta["width"] = struct.unpack("<I", head[24:27] + b"\x00")[0]
                meta["height"] = struct.unpack("<I", head[27:30] + b"\x00")[0]
            elif chunk == b"VP8 " and len(head) >= 22:
                meta["width"] = struct.unpack("<H", head[18:20])[0]
                meta["height"] = struct.unpack("<H", head[20:22])[0]
            elif chunk == b"VP8L" and len(head) >= 25:
                bits = struct.unpack("<I", head[21:25])[0]
                meta["width"] = (bits & 0x3FFF) + 1
                meta["height"] = ((bits >> 14) & 0x3FFF) + 1
        return meta
    except Exception:
        return {}


# ============================================================
# Case 执行
# ============================================================
def run_case(case: Dict) -> Dict:
    case_id = case["case_id"]
    keep_patterns = case.get("expected_keep_patterns", [])
    max_sel = case.get("expected_max_images", 6)

    if case.get("source") == "real_events_20260808":
        images = load_real_images(case["note_id"])
        if not images:
            return {"case_id": case_id, "status": "SKIP", "reason": "note 数据未找到"}
        meta_provider = real_metadata_provider
    else:
        images = synth_images(case.get("image_spec", {}))
        meta_provider = synth_metadata_provider(case.get("image_spec", {}))

    before = len(images)
    selected = select_images(images, metadata_provider=meta_provider,
                             max_select=max_sel)
    after = len(selected)

    # metrics
    reduction = image_reduction_rate(before, after)
    tokens = token_saving_estimate(before, after)

    # 信息保留：给原图/选中图附加 metadata + score
    # 注意：selected_metas 按 router 输出顺序（selected 列表），
    # 才能正确检查"知识长图优先"的排序。
    from collector.image_router.scorer import score_image

    original_metas = []
    meta_by_url = {}
    for url in images:
        meta = {"url": url, **meta_provider(url)} if meta_provider else {"url": url}
        scored = score_image(meta)
        meta["score"] = scored["score"]
        original_metas.append(meta)
        meta_by_url[url] = meta

    selected_metas = [meta_by_url[u] for u in selected if u in meta_by_url]

    preservation = information_preservation(original_metas, selected_metas,
                                            keep_patterns)

    return {
        "case_id": case_id,
        "title": case.get("title", ""),
        "note_id": case.get("note_id", ""),
        "status": "OK",
        "before": before,
        "after": after,
        "reduction_rate": reduction,
        "token_saving": tokens,
        "preservation": preservation,
        "selected_urls": selected,
    }


# ============================================================
# 报告
# ============================================================
def print_report(results: List[Dict]) -> None:
    print("=" * 44)
    print("Image Router Eval Report")
    print("=" * 44)
    for r in results:
        if r.get("status") == "SKIP":
            print(f"\nCase: {r['case_id']}  [SKIP] {r.get('reason')}")
            continue
        print(f"\nCase: {r['case_id']}")
        if r.get("title"):
            print(f"  {r['title']}")
        print(f"  Before: {r['before']} images")
        print(f"  After:  {r['after']} images")
        print(f"  Reduction: {r['reduction_rate'] * 100:.0f}%")
        ts = r["token_saving"]
        print(f"  Estimated token saved: {ts['saved_tokens']}"
              f" ({ts['before_tokens']} -> {ts['after_tokens']})")
        pres = r["preservation"]
        status = "PASS" if pres["pass"] else "FAIL"
        print(f"  Preservation: {status}")
        for k, v in pres["checks"].items():
            print(f"    - {k}: {'✅' if v else '❌'} {pres['details'].get(k, '')}")
    print("\n" + "=" * 44)


def main() -> int:
    ap = argparse.ArgumentParser(description="Image Router Eval Runner")
    ap.add_argument("--case", default=None, help="只跑指定 case_id")
    args = ap.parse_args()

    cases = load_cases()
    if args.case:
        cases = [c for c in cases if c["case_id"] == args.case]

    results = [run_case(c) for c in cases]
    print_report(results)

    # 结构化结果保存
    RESULTS_FILE.write_text(
        json.dumps({"cases": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"结果已保存: {RESULTS_FILE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
