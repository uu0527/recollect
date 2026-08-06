"""
LLM Provider Layer - Factory（Phase 3）

get_provider(stage) 返回 LLMClient（抽象接口类型）。
- 调用方只依赖 LLMClient 接口，不感知具体实现
- P5 调用时传 force_new=True，确保与 P3 provider 实例物理隔离
- api_key 缺失时 warning 后自动回退 mock（不抛异常阻断 pipeline）
"""
from __future__ import annotations

import sys
from typing import Any, Dict

from pipeline._llm.base import LLMClient


def get_provider(stage: str, force_new: bool = False) -> LLMClient:
    """
    根据 config.MODEL_CONFIG[stage] 构建并返回 LLMClient。

    参数
    ----
    stage     : "p2" | "p3" | "p5" | "p6" | 其他（fallback 到 "default"）
    force_new : True → 每次返回新实例（P5 专用）

    返回类型是 LLMClient（抽象接口），调用方不应 isinstance 检查具体类。
    """
    from config import MODEL_CONFIG  # 延迟 import，避免模块级循环

    stage_cfg: Dict[str, Any] = _resolve_stage_cfg(stage, MODEL_CONFIG)
    provider_name: str = stage_cfg["provider"]
    temperature: float = float(stage_cfg["temperature"])

    return _build(provider_name, temperature, MODEL_CONFIG)


# ----------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------

def _resolve_stage_cfg(stage: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    将 MODEL_CONFIG[stage] 规范化为 {"provider": str, "temperature": float} dict。
    支持两种写法：
      - 完整 dict: {"provider": "kimi", "temperature": 0.3}
      - 快捷 str:  "kimi"（等同 {"provider": "kimi", "temperature": 默认值}）
    """
    raw = cfg.get(stage)
    default_provider: str = cfg.get("default", "mock")
    default_temperature: float = float(cfg.get("temperature", 0.0))

    if isinstance(raw, dict):
        return {
            "provider": raw.get("provider", default_provider),
            "temperature": float(raw.get("temperature", default_temperature)),
        }
    if isinstance(raw, str):
        return {"provider": raw, "temperature": default_temperature}
    # stage 不在 config 中，用全局默认
    return {"provider": default_provider, "temperature": default_temperature}


def _build(provider_name: str, temperature: float, cfg: Dict[str, Any]) -> LLMClient:
    """构建对应 provider 的 LLMClient 实例"""
    from pipeline._llm.mock import MockLLMClient

    if provider_name == "mock":
        return MockLLMClient(temperature=temperature)

    if provider_name in ("openai", "kimi", "deepseek", "qwen", "hunyuan","zhipu"):
        from pipeline._llm.openai_provider import OpenAICompatibleClient

        _key_env = {
            "openai": "openai_api_key",
            "kimi": "kimi_api_key",
            "deepseek": "deepseek_api_key",
            "qwen": "qwen_api_key",
            "hunyuan": "hunyuan_api_key",
            "zhipu": "zhipu_api_key",
        }
        api_key: str = cfg.get(_key_env[provider_name], "")
        if not api_key:
            print(
                f"[LLM factory] WARNING: {provider_name} api_key 为空，"
                f"请设置环境变量 {_key_env[provider_name].upper()}。"
                f"自动回退到 mock。",
                file=sys.stderr,
            )
            return MockLLMClient(temperature=temperature)

        model: str | None = cfg.get(f"{provider_name}_model") or None
        return OpenAICompatibleClient(
            provider=provider_name,
            api_key=api_key,
            model=model,
            temperature=temperature,
            timeout=int(cfg.get("timeout", 30)),
            max_retries=int(cfg.get("max_retries", 3)),
        )

    raise ValueError(
        f"[LLM factory] 未知 provider: {provider_name!r}，"
        f"可选: mock / openai / kimi / deepseek / qwen / hunyuan / zhipu"
    )
