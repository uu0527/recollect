"""
LLM Provider Layer - Mock 实现（Phase 3）

设计目标：
  模拟真实 provider 行为：接收 system/user prompt，按 schema 结构返回合理假数据。
  不是包装旧启发式逻辑，而是：
    1. 解析 prompt 中的 schema 字段期望
    2. 构造最小合法 dict 返回
  这样 eval / 单元测试可以在不调用真实 API 的情况下验证调用链路完整性。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pipeline._llm.base import LLMClient, validate_schema


class MockLLMClient(LLMClient):
    """
    Mock provider。
    - complete()      → 返回含 prompt 摘要的占位文本
    - json_complete() → 根据 schema 中的 required 字段，返回最小合法 dict
    调用方式与真实 provider 完全相同，确保调用链路可被端到端测试。
    """

    provider_name = "mock"

    def __init__(self, temperature: float = 0.0, **_kw):
        self.temperature = temperature

    # ----------------------------------------------------------------
    # 接口实现
    # ----------------------------------------------------------------

    def complete(self, system: str, user: str, **kw) -> str:
        """返回占位文本，包含 prompt 摘要便于调试"""
        return (
            f"[mock.complete] provider={self.provider_name} "
            f"system={system[:40]!r}... user={user[:40]!r}..."
        )

    def json_complete(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
        **kw,
    ) -> Dict[str, Any]:
        """
        根据 schema 的 required + properties 构造最小合法 dict。
        若无 schema，返回带调试信息的占位 dict。
        不抛异常，模拟"LLM 总是成功返回"的理想路径。
        """
        result = _scaffold_from_schema(schema) if schema else {"_mock": True}
        result["_provider"] = self.provider_name

        # 做一次 schema 校验（验证 scaffold 本身是合法的）
        if schema:
            try:
                # 去掉 _provider 再校验（避免 schema 不含此字段时报错）
                clean = {k: v for k, v in result.items() if not k.startswith("_")}
                validate_schema(clean, schema)
            except ValueError:
                pass  # mock 不因 schema 校验失败而中断

        return result


# ----------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------

def _scaffold_from_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """
    根据 JSON Schema 的 required + properties 生成最小合法骨架 dict。
    类型推断：string→"", number→0, integer→0, boolean→False,
              array→[], object→{}, 其他→null
    """
    props: Dict[str, Any] = schema.get("properties", {})
    required: List[str] = schema.get("required", list(props.keys()))
    result: Dict[str, Any] = {}
    for key in required:
        prop_def = props.get(key, {})
        result[key] = _default_for_type(prop_def)
    return result


def _default_for_type(prop_def: Dict[str, Any]) -> Any:
    """为单个 property 返回类型默认值"""
    t = prop_def.get("type", "string")
    if isinstance(t, list):
        t = t[0]  # 取第一个类型
    if t == "string":
        # 若有 enum，取第一个合法值
        enum = prop_def.get("enum")
        return enum[0] if enum else ""
    if t in ("number", "integer"):
        minimum = prop_def.get("minimum", 0)
        return minimum
    if t == "boolean":
        return False
    if t == "array":
        items = prop_def.get("items", {})
        # 返回含一个元素的列表（保证 minItems 通过）
        return [_default_for_type(items)]
    if t == "object":
        return _scaffold_from_schema(prop_def)
    return None
