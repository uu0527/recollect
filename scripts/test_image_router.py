"""
Image Router 单元测试
覆盖: Case1(12图去重+长图) / Case2(封面+知识长图) / Case3(10张普通) / scorer 规则
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.image_router import select_images, select_images_simple  # noqa: E402
from collector.image_router.scorer import score_image  # noqa: E402


def _mk_urls(n, prefix="https://x.com/img"):
    return [f"{prefix}{i}.webp" for i in range(n)]


def _meta_provider(width=800, height=800, size=100 * 1024):
    """构造 metadata_provider：所有图同尺寸"""
    def provider(url):
        return {"width": width, "height": height, "size_bytes": size}
    return provider


def test_case1_12_images_dedup_tall():
    """Case1: 12 图（6 重复 + 3 长图 + 3 普通）→ <=6 张且长图全保留"""
    urls = []
    # 3 张长图（高>宽）
    for i in range(3):
        urls.append(f"https://x.com/tall{i}.webp")
    # 3 张普通
    for i in range(3):
        urls.append(f"https://x.com/norm{i}.webp")
    # 6 张重复（同一普通 URL）
    dup_url = "https://x.com/norm0.webp"
    urls += [dup_url] * 6

    def provider(url):
        base = url.split("/")[-1]
        if base.startswith("tall"):
            return {"width": 800, "height": 1500, "size_bytes": 200 * 1024}  # 长图+大
        return {"width": 800, "height": 800, "size_bytes": 100 * 1024}

    sel = select_images(urls, metadata_provider=provider)
    assert len(sel) <= 6, f"输出 {len(sel)} > 6"
    # 长图全保留
    for i in range(3):
        assert f"https://x.com/tall{i}.webp" in sel, f"长图 {i} 丢失"
    # 重复 URL 最多 1 张
    assert sum(1 for u in sel if u == dup_url) <= 1, f"重复图未去重: {sel}"
    print(f"PASS case1: {len(urls)}→{len(sel)} 张, 长图全保留")


def test_case2_cover_then_knowledge():
    """Case2: 封面 + 知识长图 → 知识长图优先"""
    urls = ["https://x.com/cover.webp"] + ["https://x.com/knowledge.webp"]

    def provider(url):
        if url.endswith("knowledge.webp"):
            return {"width": 800, "height": 2000, "size_bytes": 300 * 1024}  # 长图+大
        return {"width": 800, "height": 800, "size_bytes": 30 * 1024}  # 封面小

    sel = select_images(urls, metadata_provider=provider)
    # 两张都可能被选（cover -5 但非重复），但 knowledge 分更高
    assert "https://x.com/knowledge.webp" in sel, "知识长图未保留"
    # 排序：knowledge 应在前
    assert sel[0] == "https://x.com/knowledge.webp", f"知识长图应优先, got {sel}"
    print(f"PASS case2: 封面+知识长图 → 知识图优先 {sel}")


def test_case3_10_normal_photos():
    """Case3: 10 张普通照片 → 最多 6 张"""
    urls = _mk_urls(10)
    sel = select_images(urls, metadata_provider=_meta_provider())
    assert len(sel) <= 6, f"输出 {len(sel)} > 6"
    # 所有图同分 → 取前 6（普通图上限 3？高分阈值未达 → normal 补 3）
    # 注意: 无长图/大图 → 全部普通 → 最多 max_normal=3
    assert len(sel) <= 3, f"普通图应最多 3 张（无高分）, got {len(sel)}"
    print(f"PASS case3: 10 张普通 → {len(sel)} 张（普通图上限 3）")


def test_scorer_rules():
    """scorer 各规则独立验证"""
    # 长图 +30
    s = score_image({"url": "u", "index": 1, "width": 800, "height": 1500})
    assert "tall_image" in s["reason"] and s["score"] >= 30
    # 高分辨率 +20
    s2 = score_image({"url": "u", "index": 1, "width": 1200, "height": 800})
    assert "high_res" in s2["reason"] and s2["score"] >= 20
    # 大文件 +20
    s3 = score_image({"url": "u", "index": 1, "size_bytes": 200 * 1024})
    assert "large_file" in s3["reason"]
    # 小文件 -10（不删除）
    s4 = score_image({"url": "u", "index": 1, "size_bytes": 10 * 1024})
    assert "small_file" in s4["reason"] and s4["score"] == -10
    # 重复 -50
    s5 = score_image({"url": "u", "index": 1, "is_duplicate": True})
    assert "duplicate_url" in s5["reason"] and s5["score"] == -50
    # 封面 -5
    s6 = score_image({"url": "u", "index": 0})
    assert "cover_position" in s6["reason"] and s6["score"] == -5
    print("PASS scorer: 长图/高分辨率/大小/重复/封面 规则全验证")


def test_simple_no_metadata():
    """无 metadata：只去重 + 封面降分"""
    urls = ["a.webp", "b.webp", "a.webp"]
    sel = select_images_simple(urls)
    # 去重后 a 只出现 1 次
    assert sel.count("a.webp") <= 1
    assert "b.webp" in sel
    print(f"PASS simple: {urls} → {sel}")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n结果: {passed} 通过 / {len(fns) - passed} 失败")
    sys.exit(0 if passed == len(fns) else 1)
