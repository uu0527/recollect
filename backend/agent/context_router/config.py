"""
Context Router 配置

threshold 可配置（不 hardcode），通过环境变量覆盖。
"""
from __future__ import annotations

import os


class RouterConfig:
    """Router 配置（环境变量可覆盖）"""

    # 相似度阈值: score >= threshold 才注入 context
    THRESHOLD: float = float(os.environ.get("CONTEXT_ROUTER_THRESHOLD", "0.12"))

    # 策略: lexical（V1，token 重叠 + 实体命中）
    STRATEGY: str = os.environ.get("CONTEXT_ROUTER_STRATEGY", "lexical")

    # 未来: embedding 策略（装 sentence-transformers 后启用）
    # EMBEDDING_MODEL = os.environ.get("CONTEXT_ROUTER_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
