"""
Image Router - Scorer（MVP）

职责：
  对单张图片生成 Value Score（0~100+ 可超，含负分），输出 score + reason。
  只使用低成本信号（URL 去重 / 尺寸比例 / 分辨率 / 文件大小 / 顺序），
  不调用 OCR、Embedding、额外模型。

规则（叠加）：
  1. URL 去重        -50（相同 URL 只保留一次，重复出现降分）
  2. 长图比例        +30（height/width > 1.2，可能是教程/知识卡片）
  3. 高分辨率        +20（width>=1000 或 height>=1000）
  4. 文件大小 >150KB +20；<20KB -10（不删除，小 webp 可能仍有价值）
  5. 封面顺序(第1张) -5（不删除，除非后续有更高分图片）

输入 metadata:
  {"url": str, "index": int, "width": int|None, "height": int|None,
   "size_bytes": int|None}
输出:
  {"url": str, "score": float, "reason": [str,...]}
"""
from __future__ import annotations

from typing import Dict, List, Optional

DEFAULT_REASON = "default"


def score_image(meta: Dict) -> Dict:
    """对单张图片评分"""
    url = meta.get("url", "")
    score = 0.0
    reasons: List[str] = []

    # 1. URL 去重（-50）
    if meta.get("is_duplicate"):
        score -= 50
        reasons.append("duplicate_url")

    # 2. 长图比例（+30）
    w = meta.get("width")
    h = meta.get("height")
    if w and h and w > 0 and (h / w) > 1.2:
        score += 30
        reasons.append("tall_image")

    # 3. 高分辨率（+20）
    if (w and w >= 1000) or (h and h >= 1000):
        score += 20
        reasons.append("high_res")

    # 4. 文件大小
    size = meta.get("size_bytes")
    if size is not None:
        if size > 150 * 1024:
            score += 20
            reasons.append("large_file")
        elif size < 20 * 1024:
            score -= 10
            reasons.append("small_file")

    # 5. 封面顺序（第 1 张 -5）
    if meta.get("index") == 0:
        score -= 5
        reasons.append("cover_position")

    if not reasons:
        reasons.append(DEFAULT_REASON)

    return {"url": url, "score": round(score, 1), "reason": reasons}
