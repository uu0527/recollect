"""
pipeline/_llm/ — 统一 LLM 接口层（Phase 3）
公共 API：LLMClient（接口）、get_provider（工厂）
具体实现：MockLLMClient、OpenAICompatibleClient
辅助工具：extract_json、validate_schema（供 stage 内部直接使用）
"""
from pipeline._llm.base import LLMClient, extract_json, validate_schema
from pipeline._llm.mock import MockLLMClient
from pipeline._llm.openai_provider import OpenAICompatibleClient
from pipeline._llm.factory import get_provider

__all__ = [
    "LLMClient",
    "MockLLMClient",
    "OpenAICompatibleClient",
    "get_provider",
    "extract_json",
    "validate_schema",
]
