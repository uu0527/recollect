"""
LLM Provider Layer - OpenAI 兼容实现（Phase 3）

覆盖 OpenAI / Kimi / DeepSeek 三家（全部兼容 openai SDK，只换 base_url + api_key）。
依赖：openai>=1.0.0（pyproject.toml [llm] extras）

json_complete 策略：
  - 最多重试 max_retries 次
  - 每次重试在 user prompt 后追加 schema 约束提示
  - 全部失败抛 ValueError（降级由调用方决定，不写死在 provider 里）
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pipeline._llm.base import LLMClient, extract_json, validate_schema

# 各 provider base_url（全部兼容 openai SDK）
_BASE_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_vision": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "hunyuan": "https://api.hunyuan.cloud.tencent.com/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
}

# 各 provider 默认 model
_DEFAULT_MODELS: Dict[str, str] = {
    "openai": "gpt-4o-mini",
    "kimi": "moonshot-v1-8k",
    "deepseek": "deepseek-chat",
    "qwen": "qwen-plus",
    "qwen_vision": "qwen3-vl-plus",
    "hunyuan": "hunyuan-turbo",
    "zhipu": "glm-4-flash",
}


class OpenAICompatibleClient(LLMClient):
    """
    通过 openai SDK 连接 OpenAI / Kimi / DeepSeek。
    provider_name 属性标识具体厂商，供日志/eval 追踪。
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: Optional[str] = None,
        temperature: float = 0.0,
        timeout: int = 30,
        max_retries: int = 3,
        **_kw,
    ):
        if provider not in _BASE_URLS:
            raise ValueError(
                f"不支持的 provider: {provider!r}，可选: {list(_BASE_URLS)}"
            )
        # 保留 provider_name 属性，供日志/eval 使用
        self.provider_name: str = provider
        self.model: str = model or _DEFAULT_MODELS[provider]
        self.temperature: float = temperature
        self.timeout: int = timeout
        self.max_retries: int = max_retries

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImportError(
                "请先安装 llm 依赖：pip install 'recollect[llm]' 或 pip install openai httpx"
            ) from exc

        self._client = OpenAI(
            api_key=api_key,
            base_url=_BASE_URLS[provider],
            timeout=float(timeout),
            max_retries=0,  # 重试逻辑由本层统一管理
        )

    # ----------------------------------------------------------------
    # 接口实现
    # ----------------------------------------------------------------

    def complete(self, system: str, user: str, **kw) -> str:
        """纯文本调用，带指数退避重试"""
        return self._call_with_backoff(system, user, **kw)

    def json_complete(
        self,
        system: str,
        user: str,
        schema: Optional[Dict[str, Any]] = None,
        **kw,
    ) -> Dict[str, Any]:
        """
        返回解析后的 dict。
        - 每次失败在 user prompt 后追加 JSON schema 约束提示后重试
        - max_retries 次全部失败 → 抛 ValueError（降级由调用方决定）
        """
        last_exc: Exception | None = None
        retry_user = user
        schema_hint = (
            f"\n\n请严格按以下 JSON Schema 输出，不要输出额外文字：\n{_schema_hint(schema)}"
            if schema
            else "\n\n请只输出合法 JSON 对象，不要输出额外文字。"
        )

        for attempt in range(self.max_retries + 1):
            try:
                raw = self._call_with_backoff(system, retry_user, **kw)
                parsed = extract_json(raw)
                if schema:
                    validate_schema(parsed, schema)
                return parsed
            except Exception as exc:
                last_exc = exc
                # 下一次重试追加 schema 约束提示
                retry_user = user + schema_hint + f"\n[重试 {attempt + 1}/{self.max_retries}]"

        raise ValueError(
            f"[{self.provider_name}] json_complete 失败 {self.max_retries + 1} 次: {last_exc}"
        )

    # ----------------------------------------------------------------
    # 内部工具
    # ----------------------------------------------------------------

    def _call_with_backoff(self, system: str, user: str, **kw) -> str:
        """带指数退避的单次 API 调用。
        支持 Vision：kw 可传 images=[url 或 base64 data-uri,...]，
        将 user 消息构造为多模态 content 数组（openai 兼容格式）。

        图片统一转换为 base64 data-uri 后发送（本地可验证方案）：
          - http/https URL → 下载 → base64
          - 本地路径      → 读取 → base64
          - data URI      → 原样直传
        单图失败（下载/读取）→ 跳过该图并 WARNING，不中断整篇。
        """
        images: List[str] = kw.get("images", []) or []
        messages: List[Dict] = [
            {"role": "system", "content": system},
        ]
        if images:
            # 多模态消息：content 为 [{type:text},{type:image_url},...]
            content: List[Dict[str, Any]] = [{"type": "text", "text": user}]
            for img in images:
                if img.startswith("data:"):
                    # base64 data URI：原样直传
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": img},
                    })
                elif img.startswith("http"):
                    # http/https URL → 下载 → base64（绕开远端抓取不确定性）
                    try:
                        uri = _url_to_data_uri(img)
                    except Exception as exc:
                        print(f"[{self.provider_name}] WARNING: 图片下载失败，跳过: {type(exc).__name__}: {exc}")
                        continue
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": uri},
                    })
                else:
                    # 本地路径 → base64 data-uri（文件不存在则跳过该图，不中断）
                    try:
                        uri = _local_image_to_data_uri(img)
                    except FileNotFoundError:
                        print(f"[{self.provider_name}] WARNING: 图片不存在，跳过: {img}")
                        continue
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": uri},
                    })
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": user})
        temperature = kw.get("temperature", self.temperature)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                status = getattr(exc, "status_code", None)
                # 4xx（非 429）：不重试，立即抛
                if status is not None and 400 <= status < 500 and status != 429:
                    raise
                wait = 2 ** attempt
                print(
                    f"[{self.provider_name}] API 异常 attempt={attempt + 1}/{self.max_retries} "
                    f"status={status} wait={wait}s: {exc!r}"
                )
                time.sleep(wait)

        raise RuntimeError(
            f"[{self.provider_name}] API 调用失败 {self.max_retries} 次: {last_exc}"
        )


def _schema_hint(schema: Optional[Dict[str, Any]]) -> str:
    """将 schema 的 required 字段整理成紧凑提示文本"""
    if not schema:
        return "{}"
    required = schema.get("required", [])
    props = schema.get("properties", {})
    lines = []
    for k in required:
        t = props.get(k, {}).get("type", "any")
        lines.append(f'  "{k}": <{t}>')
    return "{\n" + ",\n".join(lines) + "\n}"


def _local_image_to_data_uri(path: str) -> str:
    """本地图片路径 → base64 data URI（带 mime 前缀）"""
    import base64
    import mimetypes
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"图片不存在: {path}")
    mime = mimetypes.guess_type(p.name)[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _url_to_data_uri(url: str, timeout: float = 20.0, max_bytes: int = 5 * 1024 * 1024) -> str:
    """http/https 图片 URL → base64 data URI（下载后本地转换）

    带 UA 请求；超过 max_bytes 抛错（避免超大图）；
    单图失败由调用方捕获（跳过该图，不中断整篇）。
    """
    import base64
    import mimetypes
    import urllib.request
    from urllib.parse import urlparse

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"图片过大: {len(data)} bytes > {max_bytes}")
    # mime：优先响应头，其次按扩展名
    ctype = resp.headers.get("Content-Type", "")
    if not ctype or "image" not in ctype:
        ctype = mimetypes.guess_type(urlparse(url).path)[0] or "image/jpeg"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{ctype};base64,{b64}"
