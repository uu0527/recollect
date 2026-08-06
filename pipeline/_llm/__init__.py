"""
pipeline/_llm/ — 统一 LLM 接口层（Phase 3 / 3.5）
公共 API：LLMClient（接口）、get_provider（工厂）、get_stage_provider（智能路由）
具体实现：MockLLMClient、OpenAICompatibleClient
路由能力：ModelRouter / TaskClassifier / TrackedLLMClient（Token 统计）
辅助工具：extract_json、validate_schema（供 stage 内部直接使用）
"""
from pipeline._llm.base import LLMClient, extract_json, validate_schema
from pipeline._llm.mock import MockLLMClient
from pipeline._llm.openai_provider import OpenAICompatibleClient
from pipeline._llm.factory import get_provider
from pipeline._llm.router import get_stage_provider, debug_route
from pipeline._llm.usage import (
    record_usage, daily_usage, is_over_limit, get_cost_summary, load_usage_log,
)

__all__ = [
    "LLMClient",
    "MockLLMClient",
    "OpenAICompatibleClient",
    "get_provider",
    "get_stage_provider",
    "debug_route",
    "record_usage",
    "daily_usage",
    "is_over_limit",
    "get_cost_summary",
    "load_usage_log",
    "extract_json",
    "validate_schema",
]
