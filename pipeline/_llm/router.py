"""
LLM Model Router（智能模型路由）

设计目标：
  - 默认使用低成本模型（hunyuan）
  - 只有高价值/复杂任务才调用 DeepSeek
  - 按时间调度切换默认模型（只影响默认选择，不覆盖复杂度判断）
  - DeepSeek 每日 Token 限额保护（超限自动切混元）
  - 失败自动切换（deepseek ↔ hunyuan 互切），记录 fallback 原因
  - 每次调用记录日志（logs/model_usage.json）

使用方式（调用方最小改动）：
  from pipeline._llm.router import get_stage_provider
  provider = get_stage_provider("p3", task_id=..., task_type="summary",
                                text=note.content, note_id=note.note_id)
  result = provider.json_complete(system, user, schema=None)

现有 pipeline 调用方只改一行：get_provider(stage) → get_stage_provider(stage, ...)
不破坏：Mock 模式 / Eval 系统 / Provider 接口（返回仍是 LLMClient）。
"""
from __future__ import annotations

import re
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pipeline._llm.base import LLMClient
from pipeline._llm.usage import record_usage, is_over_limit


# ----------------------------------------------------------------
# 常量
# ----------------------------------------------------------------
LEVEL_1 = "LEVEL_1"   # 简单任务 → 低成本模型（hunyuan）
LEVEL_2 = "LEVEL_2"   # 中等任务 → 默认低成本，效果不足升级 deepseek
LEVEL_3 = "LEVEL_3"   # 复杂任务 → 直接 deepseek

# 阶段默认等级
STAGE_DEFAULT_LEVEL: Dict[str, str] = {
    "p2": LEVEL_1,  # 内容筛选：分类/标签/价值判断 → 低成本
    "p3": LEVEL_2,  # 归纳：按内容复杂度自动升降级
    "p5": LEVEL_3,  # 审计：高质量模型 + 与 P3 模型隔离
    "p6": LEVEL_1,  # 检索问答（当前不调 LLM，预留）
}

# provider 角色
ROLE_COST = "hunyuan"      # 成本优化模型
ROLE_QUALITY = "deepseek"  # 高质量推理模型
ROLE_FALLBACK = "qwen"     # 兜底模型（key 可用时承担任何任务）

# 复杂任务特征关键词（技术/推理/多步骤）
_COMPLEX_KEYWORDS = [
    "代码", "python", "pandas", "sql", "算法", "架构", "系统设计",
    "原理", "源码", "debug", "重构", "性能", "对比", "方案", "架构图",
    "简历", "面试", "面经", "题库", "落户", "流程", "材料清单", "时间线",
    "教程", "步骤", "指南", "攻略", "模板", "清单", "实测", "踩坑",
]


# ----------------------------------------------------------------
# TaskClassifier：任务复杂度分级
# ----------------------------------------------------------------
class TaskClassifier:
    """根据文本特征 + 任务类型，输出 LEVEL_1/2/3"""

    _COMPLEX_RE = re.compile("|".join(re.escape(k) for k in _COMPLEX_KEYWORDS), re.IGNORECASE)

    def classify(self, text: str = "", task_type: str = "") -> str:
        # 显式 task_type 指定
        if task_type in ("code", "architecture", "analysis", "deep_reasoning"):
            return LEVEL_3
        if task_type in ("classify", "tagging", "extract", "format"):
            return LEVEL_1

        text = text or ""
        length = len(text)

        # 长文本 → 复杂
        if length > 2000:
            return LEVEL_3
        # 中等长度 + 复杂关键词 → 复杂
        if length > 500 and self._COMPLEX_RE.search(text):
            return LEVEL_3
        # 中等长度
        if 200 < length <= 2000:
            return LEVEL_2
        # 短文本 + 复杂关键词（技术内容浓缩）→ 中等
        if self._COMPLEX_RE.search(text):
            return LEVEL_2
        return LEVEL_1


# ----------------------------------------------------------------
# 时间调度
# ----------------------------------------------------------------
def _current_default_model(schedule_enabled: bool, schedule: List[Dict]) -> str:
    """根据当前系统时间返回默认模型（只作为默认选择，不覆盖复杂度判断）"""
    if not schedule_enabled or not schedule:
        return ROLE_COST
    now = datetime.now().strftime("%H:%M")
    for slot in schedule:
        start, end = slot.get("start", "00:00"), slot.get("end", "23:59")
        # 支持跨天区间（如 22:00-02:00）
        if start <= end:
            if start <= now <= end:
                return slot.get("default_model", ROLE_COST)
        else:
            if now >= start or now <= end:
                return slot.get("default_model", ROLE_COST)
    return ROLE_COST


# ----------------------------------------------------------------
# ModelRouter
# ----------------------------------------------------------------
class ModelRouter:
    """
    智能模型路由核心。
    - resolve(stage, ...) → (provider_name, level, reason)
    - get_provider(stage, ...) → LLMClient（已带 token 统计包装）
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg: Dict[str, Any] = config or {}
        self.classifier = TaskClassifier()
        self._client_cache: Dict[str, LLMClient] = {}  # (stage) → client

    # ------------------------------------------------------------
    # 路由解析
    # ------------------------------------------------------------
    def resolve(
        self,
        stage: str,
        task_type: str = "",
        text: str = "",
        force_model: Optional[str] = None,
    ) -> Tuple[str, str, str]:
        """
        返回 (provider_name, level, reason)。
        reason 用于日志/调试，如 "schedule|p3|LEVEL_2|default:hunyuan"。
        已内置 key 有效性校验：目标 provider 无有效 key 时自动降级到下一个可用 provider。
        """
        # 0) 显式指定模型（最高优先级，测试/调试用）
        if force_model:
            if _provider_available(force_model):
                return force_model, self._level_for(force_model), f"forced:{force_model}"
            return ROLE_COST, LEVEL_2, f"forced:{force_model}|key_missing→cost"

        # 0.5) P5 审计模型隔离：与 P3 用不同模型，防止自评
        if stage == "p5":
            p3_provider = _last_used_provider("p3")
            isolated = ROLE_QUALITY if p3_provider == ROLE_COST else ROLE_COST
            # key 校验：隔离目标不可用则取第一个可用模型（≠ p3 用过的）
            if not _provider_available(isolated):
                for cand in (ROLE_COST, ROLE_QUALITY, ROLE_FALLBACK):
                    if cand != p3_provider and _provider_available(cand):
                        return cand, LEVEL_3, f"p5_isolation|{isolated}_unavailable→{cand}"
                # 单 provider 环境：无法隔离，退而求其次用第一个可用模型（记录 degraded）
                for cand in (ROLE_COST, ROLE_QUALITY, ROLE_FALLBACK):
                    if _provider_available(cand):
                        return cand, LEVEL_3, f"p5_isolation|degraded_single_provider→{cand}"
            return isolated, LEVEL_3, f"p5_isolation|p3_used:{p3_provider or 'none'}"

        # 1) 复杂度分级
        level = self.classifier.classify(text=text, task_type=task_type)
        stage_default = STAGE_DEFAULT_LEVEL.get(stage, LEVEL_2)
        # 阶段默认等级更高时，取其高者（如 p5 强制 LEVEL_3）
        level = _max_level(level, stage_default)

        # 2) DeepSeek 限额保护
        if is_over_limit(ROLE_QUALITY):
            return self._first_available((ROLE_COST, ROLE_FALLBACK)), level, \
                f"deepseek_daily_limit|{level}"

        # 3) 按等级选模型（含 key 校验 + 逐级降级）
        if level == LEVEL_3:
            chosen = self._first_available((ROLE_QUALITY, ROLE_COST, ROLE_FALLBACK))
            tag = "complex" if chosen == ROLE_QUALITY else \
                ("complex|quality_unavailable→cost" if chosen == ROLE_COST else
                 "complex|quality/cost_unavailable→fallback")
            return chosen, level, f"{tag}|{level}"
        if level == LEVEL_2:
            # 中等任务：时间调度决定默认；混元不可用时逐级降级
            default = _current_default_model(
                bool(self.cfg.get("schedule_enabled", True)),
                self.cfg.get("schedule", []),
            )
            if default == ROLE_QUALITY and _provider_available(ROLE_QUALITY):
                return ROLE_QUALITY, level, f"medium|{level}|default:{default}"
            chosen = self._first_available((ROLE_COST, ROLE_FALLBACK, ROLE_QUALITY))
            return chosen, level, f"medium|{level}|default:{default}"
        # LEVEL_1
        chosen = self._first_available((ROLE_COST, ROLE_FALLBACK))
        if chosen is None:
            chosen = self._first_available((ROLE_QUALITY,))
        if chosen is None:
            return "mock", level, f"simple|{level}|no_key→mock"
        return chosen, level, f"simple|{level}"

    # ------------------------------------------------------------
    # 获取 provider（带 token 统计包装）
    # ------------------------------------------------------------
    def _first_available(self, providers: Tuple[str, ...]) -> str | None:
        """按优先级返回第一个有有效 key 的 provider，全不可用返回 None"""
        for p in providers:
            if _provider_available(p):
                return p
        return None
    def get_provider(
        self,
        stage: str,
        task_id: str = "",
        task_type: str = "",
        text: str = "",
        force_new: bool = False,
        force_model: Optional[str] = None,
        fallback_reason: str = "",
    ) -> LLMClient:
        """
        返回 LLMClient（与 get_provider 同接口，调用方零感知）。
        - 已按路由规则选择 provider
        - 真实 provider 包装为 TrackedLLMClient（自动统计 token）
        """
        provider_name, level, reason = self.resolve(
            stage, task_type=task_type, text=text, force_model=force_model
        )

        # 从 factory 构建
        client = _build_provider(provider_name, stage, force_new=force_new)

        # 真实 provider 用带统计的包装（factory 可能因 key 缺失回退 mock，此时不包装）
        if client.provider_name != "mock":
            client = TrackedLLMClient(
                inner=client,
                provider=client.provider_name,
                stage=stage,
                task_id=task_id,
                task_type=task_type,
                level=level,
                route_reason=reason,
            )
        return client


# ----------------------------------------------------------------
# 带 Token 统计的包装（透明转发 + usage 上报）
# ----------------------------------------------------------------
class TrackedLLMClient(LLMClient):
    """包装真实 LLMClient，每次调用后自动上报 usage 到 logs/model_usage.json"""

    provider_name: str

    def __init__(self, inner: LLMClient, provider: str, stage: str,
                 task_id: str = "", task_type: str = "",
                 level: str = "", route_reason: str = ""):
        self._inner = inner
        self.provider_name = provider
        self.stage = stage
        self.task_id = task_id
        self.task_type = task_type
        self.level = level
        self.route_reason = route_reason
        self.model = getattr(inner, "model", provider)

    def complete(self, system: str, user: str, **kw) -> str:
        t0 = time.time()
        try:
            raw = self._inner.complete(system, user, **kw)
            self._log_usage(system, user, kw, raw=raw, success=True)
            return raw
        except Exception as exc:
            self._log_usage(system, user, kw, success=False, error=str(exc))
            raise

    def json_complete(self, system: str, user: str, schema=None, **kw) -> Dict[str, Any]:
        t0 = time.time()
        try:
            result = self._inner.json_complete(system, user, schema=schema, **kw)
            self._log_usage(system, user, kw, raw=str(result), success=True)
            return result
        except Exception as exc:
            self._log_usage(system, user, kw, success=False, error=str(exc))
            raise

    # ------------------------------------------------------------
    def _log_usage(self, system: str, user: str, kw: Dict, *,
                   raw: str = "", success: bool, error: str = "") -> None:
        # 估算 token：按中文字符约 1.5 字/token，英文约 4 字符/token（近似）
        def _est(text: str) -> int:
            cn = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
            other = max(0, len(text) - cn)
            return int(cn / 1.5 + other / 4) + 4

        input_tokens = _est(system) + _est(user)
        output_tokens = _est(raw) if raw else 0

        record_usage(
            provider=self.provider_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            task_id=self.task_id,
            stage=self.stage,
            model=self.model,
            task_type=self.task_type,
            success=success,
            error=error,
            note=f"level={self.level}|route={self.route_reason}",
        )


# ----------------------------------------------------------------
# 内部工具
# ----------------------------------------------------------------
def _max_level(a: str, b: str) -> str:
    order = {LEVEL_1: 1, LEVEL_2: 2, LEVEL_3: 3}
    return a if order.get(a, 2) >= order.get(b, 2) else b


def _level_for(provider: str) -> str:
    return LEVEL_3 if provider == ROLE_QUALITY else LEVEL_1


def _build_provider(provider_name: str, stage: str, force_new: bool = False) -> LLMClient:
    """复用 factory._build 逻辑，保持单一来源"""
    from config import MODEL_CONFIG
    from pipeline._llm.factory import _resolve_stage_cfg, _build

    stage_cfg = _resolve_stage_cfg(stage, MODEL_CONFIG)
    temperature = float(stage_cfg["temperature"])
    return _build(provider_name, temperature, MODEL_CONFIG)


def _last_used_provider(stage: str) -> str | None:
    """从 usage log 中查找某 stage 最近一次真实调用的 provider"""
    from pipeline._llm.usage import load_usage_log

    for rec in reversed(load_usage_log(limit=500)):
        if rec.get("stage") == stage and rec.get("success"):
            prov = rec.get("provider")
            if prov and prov != "mock":
                return prov
    return None


# provider → 环境变量 key 名
_PROVIDER_KEY_ENV = {
    "hunyuan": "HUNYUAN_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "QWEN_API_KEY",
    "kimi": "KIMI_API_KEY",
    "openai": "OPENAI_API_KEY",
}

# 占位符 key（无效）
_PLACEHOLDER_KEYS = {"你的key", "your-key", "your_key", "xxx", "sk-xxx", "TODO"}


def _provider_available(provider: str) -> bool:
    """检查 provider 是否有有效 API key（跳过占位符）"""
    import os

    if provider == "mock":
        return True
    env_name = _PROVIDER_KEY_ENV.get(provider)
    if not env_name:
        return False
    key = os.environ.get(env_name, "").strip()
    if not key:
        return False
    if key.lower() in _PLACEHOLDER_KEYS:
        return False
    if key.startswith("sk-") and len(key) < 20:
        return False  # 明显过短的伪 key
    return True


# ----------------------------------------------------------------
# 模块级便捷入口（调用方用这个，最接近原 get_provider 签名）
# ----------------------------------------------------------------
_router: Optional[ModelRouter] = None


def _get_router() -> ModelRouter:
    global _router
    if _router is None:
        from config import MODEL_ROUTER_CONFIG
        _router = ModelRouter(MODEL_ROUTER_CONFIG)
    return _router


def get_stage_provider(
    stage: str,
    task_id: str = "",
    task_type: str = "",
    text: str = "",
    force_new: bool = False,
    force_model: Optional[str] = None,
) -> LLMClient:
    """
    与 get_provider(stage) 签名兼容的智能路由入口。

    P2:   get_stage_provider("p2", task_id=tid, task_type="screen", text=note.content)
    P3:   get_stage_provider("p3", task_id=tid, task_type="summary", text=note.content)
    P5:   get_stage_provider("p5", task_id=tid, task_type="audit", text=raw_content, force_new=True)
    """
    return _get_router().get_provider(
        stage,
        task_id=task_id,
        task_type=task_type,
        text=text,
        force_new=force_new,
        force_model=force_model,
    )


def debug_route(stage: str, task_type: str = "", text: str = "") -> Dict:
    """调试工具：查看某个任务会被路由到哪个模型"""
    provider_name, level, reason = _get_router().resolve(stage, task_type=task_type, text=text)
    return {
        "stage": stage,
        "task_type": task_type or "-",
        "level": level,
        "provider": provider_name,
        "reason": reason,
        "text_len": len(text),
    }
