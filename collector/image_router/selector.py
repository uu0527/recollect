"""
Image Router - Selector（MVP）

职责：
  根据 scorer 的 Value Score 选择最终图片列表（selected_images）。
  不修改 RawNote 原始 images。

选择策略：
  1. URL 去重（保留首次出现）
  2. 每张计算 score
  3. 按 score 降序
  4. 高分（score >= 50）全部保留；普通图最多补充 3 张
  5. 总上限 MAX_SELECT（默认 6）安全阀

输入：
  images: List[str]  （RawNote.images 原始 URL 列表）
  metadata_provider: 可选回调，返回单张 metadata dict
                      {width, height, size_bytes}（下载/HEAD 获取）
                      None 时用默认（未知尺寸 → 只按 URL 去重/顺序评分）

输出：
  List[str] 精选 URL（按 score 降序）
"""
from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional

from collector.image_router.scorer import score_image

HIGH_SCORE_THRESHOLD = 50.0
MAX_SELECT = 6
MAX_NORMAL = 3


def _url_key(url: str) -> str:
    """URL 去重 key：去掉 query 参数后取 hash（同图不同参数视为重复）"""
    base = url.split("?")[0]
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def select_images(
    images: List[str],
    metadata_provider: Optional[Callable[[str], Dict]] = None,
    max_select: int = MAX_SELECT,
    max_normal: int = MAX_NORMAL,
    high_threshold: float = HIGH_SCORE_THRESHOLD,
) -> List[str]:
    """选择进入 Vision 的图片列表（不修改原始 images）"""
    if not images:
        return []

    # 1. URL 去重（首次出现保留，后续标记 duplicate）
    seen: Dict[str, bool] = {}
    metas: List[Dict] = []
    for idx, url in enumerate(images):
        if not url:
            continue
        key = _url_key(url)
        is_dup = key in seen
        seen[key] = True
        meta = {"url": url, "index": idx, "is_duplicate": is_dup}
        # 补充 metadata（尺寸/大小）
        if metadata_provider:
            try:
                extra = metadata_provider(url) or {}
                meta.update(extra)
            except Exception:
                pass  # metadata 获取失败不影响评分（尺寸未知）
        metas.append(meta)

    # 2. 评分（重复 URL 直接排除出选择池——保留首次出现的代表）
    scored = [score_image(m) for m in metas if not m.get("is_duplicate")]

    # 3. 排序：score 降序；同分保持原始顺序
    order = {m["url"]: i for i, m in enumerate(metas)}
    scored.sort(key=lambda s: (-s["score"], order[s["url"]]))

    # 4. 选择：高分全留 + 普通图补足（普通图最多 max_normal）
    high = [s for s in scored if s["score"] >= high_threshold]
    normal = [s for s in scored if s["score"] < high_threshold]

    selected = [s["url"] for s in high]           # 高分全部保留
    budget = max_select - len(selected)           # 剩余预算
    if budget > 0:
        selected += [s["url"] for s in normal[:min(budget, max_normal)]]

    return selected[:max_select]  # 安全阀


def select_images_simple(images: List[str], max_select: int = MAX_SELECT) -> List[str]:
    """无 metadata 的简化选择（只按 URL 去重 + 顺序评分）"""
    return select_images(images, metadata_provider=None, max_select=max_select)
