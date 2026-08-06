"""
LLM Provider Layer - 抽象接口（Phase 3）

设计原则：
- base 只定义接口契约，不写业务降级策略
- json_complete 的 schema 校验 + retry 由各 provider 自行实现
- 调用方通过 json_complete() 获得 dict，通过 complete() 获得纯文本
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class LLMClient(ABC):
    """
    统一 LLM 接口。所有 provider 必须实现这两个方法：
      complete()      → str         纯文本回复
      json_complete() → Dict        解析后的 dict，JSON 校验逻辑由子类决定
    provider_name 属性用于日志追踪。
    """

    provider_name: str = "base"

    @abstractmethod
    def complete(self, system: str, user: str, **kw) -> str:
        """返回纯文本回复"""
        ...

    @abstractmethod
    def json_complete(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
        **kw,
    ) -> Dict[str, Any]:
        """
        返回解析后的 dict。
        - schema: 可选 JSON Schema dict，用于校验输出结构
        - 失败处理策略（retry / fallback / raise）完全由子类决定
        """
        ...


# ----------------------------------------------------------------
# 共享工具函数（供子类使用，不强依赖）
# ----------------------------------------------------------------

def extract_json(text: str) -> Dict[str, Any]:
    """
    从 LLM 输出中提取 JSON 对象。
    兼容：
      - 纯 JSON
      - ```json ... ``` 代码块包裹
      - 前后有多余文字
    """
    text = text.strip()

    # 去掉 markdown 代码块
    if "```" in text:
        lines = text.splitlines()
        inner: list[str] = []
        inside = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                inside = not inside
                continue
            if inside:
                inner.append(line)
        candidate = "\n".join(inner).strip()
        if candidate:
            text = candidate

    # 提取第一个完整 {...} 块
    start = text.find("{")
    if start == -1:
        raise ValueError(f"输出中未找到 JSON 对象，原始内容: {text[:300]!r}")

    # 从 start 开始匹配括号深度，提取完整 JSON 对象
    depth = 0
    end = -1
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise ValueError(f"JSON 对象括号不闭合，原始内容: {text[:300]!r}")

    return json.loads(text[start : end + 1])


def validate_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """
    用 jsonschema 校验数据结构。
    jsonschema 未安装时静默跳过（不强依赖）。
    校验失败抛 ValueError（不抛 jsonschema.ValidationError，统一异常类型）。
    """
    try:
        import jsonschema
    except ImportError:
        return  # 未安装，跳过校验

    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise ValueError(f"JSON schema 校验失败: {exc.message}") from exc
