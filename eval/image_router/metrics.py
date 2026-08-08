"""
Image Router Eval - Metrics

离线指标（无 LLM Judge，规则驱动）：
  1. Image Reduction Rate   图片压缩率
  2. Token Saving Estimate  估算节省 token
  3. Information Preservation 信息保留（长图/高分图是否保留）
"""
from __future__ import annotations

from typing import Dict, List

# 每张图片的估算 input token（来自 Vision 成本评估：~1500/图）
TOKENS_PER_IMAGE = 1500


def image_reduction_rate(before: int, after: int) -> float:
    """图片压缩率：1 - after/before"""
    if before <= 0:
        return 0.0
    return round(1 - after / before, 4)


def token_saving_estimate(before: int, after: int,
                          tokens_per_image: int = TOKENS_PER_IMAGE) -> Dict:
    """估算 token 节省"""
    before_tokens = before * tokens_per_image
    after_tokens = after * tokens_per_image
    return {
        "before_tokens": before_tokens,
        "after_tokens": after_tokens,
        "saved_tokens": before_tokens - after_tokens,
    }


def _is_long_image(meta: Dict) -> bool:
    """长图判断：height/width > 1.2"""
    w = meta.get("width")
    h = meta.get("height")
    return bool(w and h and w > 0 and (h / w) > 1.2)


def _is_high_score(meta: Dict, threshold: float = 50.0) -> bool:
    """高分图判断"""
    return meta.get("score", 0) >= threshold


def information_preservation(
    original_metas: List[Dict],
    selected_metas: List[Dict],
    keep_patterns: List[str] | None = None,
) -> Dict:
    """信息保留检查（规则驱动，非 LLM）

    - long_image: 长图必须保留（无预算冲突时）；有预算冲突时
      验证"被丢弃的长图 score 都不高于已选最低分"（预算内最优）
    - high_score: 高分(>=50)图保留（同上语义）
    - knowledge_first: 高分长图应排在普通图之前（排序检查）
    - best_in_budget: 通用最优性——被丢弃图 score <= 已选最低分
    """
    keep_patterns = keep_patterns or []
    results: Dict[str, bool] = {}
    details: Dict[str, str] = {}

    selected_urls = {m.get("url") for m in selected_metas}
    selected_scores = [m.get("score", 0) for m in selected_metas]
    min_selected = min(selected_scores) if selected_scores else 0
    discarded = [m for m in original_metas if m["url"] not in selected_urls]

    def _check_keep(name: str, pred) -> None:
        """通用保留检查：无丢弃→PASS；有丢弃但都是低分→PASS（预算内最优）"""
        dropped = [m for m in discarded if pred(m)]
        if not dropped:
            results[name] = True
            details[name] = "全部保留"
        else:
            max_dropped = max((m.get("score", 0) for m in dropped), default=0)
            ok = max_dropped <= min_selected  # 被丢弃的都 <= 已选最低分
            results[name] = ok
            details[name] = (
                f"丢弃 {len(dropped)} 张(最高分 {max_dropped} ≤ 已选最低 {min_selected})"
                if ok else f"丢弃 {len(dropped)} 张且分数高于已选最低分 {min_selected}"
            )

    if "long_image" in keep_patterns:
        _check_keep("long_image", _is_long_image)

    if "high_score" in keep_patterns:
        _check_keep("high_score", lambda m: _is_high_score(m))

    if "knowledge_first" in keep_patterns:
        # 排序检查：高分长图应在前
        long_idx = [i for i, m in enumerate(selected_metas)
                    if _is_long_image(m) and _is_high_score(m)]
        normal_idx = [i for i, m in enumerate(selected_metas)
                      if not (_is_long_image(m) and _is_high_score(m))]
        ok = (not long_idx) or (not normal_idx) or long_idx[0] < normal_idx[0]
        results["knowledge_first"] = ok
        details["knowledge_first"] = (
            "知识长图优先于普通图" if ok else "知识长图未排在前面"
        )

    if not results:
        # 无明确 keep_patterns：默认检查——选中列表非空
        results["selected_non_empty"] = len(selected_metas) > 0
        details["selected_non_empty"] = f"选中 {len(selected_metas)} 张"

    overall = all(results.values())
    return {"pass": overall, "checks": results, "details": details}
