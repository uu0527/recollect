"""
LLM Usage Tracker（Token 统计与每日限额）

- 每次 LLM 调用后由 provider 上报 usage（input/output tokens）
- 按 (provider, date) 累加，支持每日限额检查
- 数据持久化到 logs/model_usage.json（供成本分析 / Eval 归因）

线程安全：用文件锁近似（单进程 pipeline 场景足够）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 日志目录（项目根 /logs）
BASE_DIR = Path(__file__).resolve().parents[2]
LOG_DIR = BASE_DIR / "logs"
USAGE_FILE = LOG_DIR / "model_usage.json"
DAILY_STATS_FILE = LOG_DIR / "token_daily.json"

_lock = threading.Lock()

# 每 1K token 的成本（USD，近似；可配置覆盖）
_COST_PER_1K: Dict[str, Dict[str, float]] = {
    "deepseek": {"input": 0.0011, "output": 0.0022},   # deepseek-chat 官方价
    "zhipu":    {"input": 0.0001, "output": 0.0002},   # glm-4-flash 官方价（约 ¥0.0007/1K in）
    "hunyuan": {"input": 0.0004, "output": 0.0008},    # 混元 turbo 官方价（约，兼容保留）
    "qwen":    {"input": 0.0005, "output": 0.0010},    # qwen-plus 约
    "kimi":    {"input": 0.0006, "output": 0.0012},    # moonshot-v1-8k 约
    "openai":  {"input": 0.0005, "output": 0.0015},    # gpt-4o-mini 约
    "mock":    {"input": 0.0,    "output": 0.0},
}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load_daily() -> Dict[str, Dict[str, int]]:
    if DAILY_STATS_FILE.exists():
        try:
            return json.loads(DAILY_STATS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_daily(data: Dict) -> None:
    DAILY_STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    DAILY_STATS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ----------------------------------------------------------------
# 公共 API
# ----------------------------------------------------------------

def record_usage(
    provider: str,
    input_tokens: int,
    output_tokens: int,
    *,
    task_id: str = "",
    stage: str = "",
    model: str = "",
    task_type: str = "",
    success: bool = True,
    error: str = "",
    note: str = "",
) -> Dict:
    """
    记录一次模型调用。
    返回本次调用的 usage dict（含 estimated_cost）。
    """
    cost = _estimate_cost(provider, input_tokens, output_tokens)
    record = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "date": _today(),
        "task_id": task_id,
        "stage": stage,
        "model": model,
        "provider": provider,
        "task_type": task_type,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
        "estimated_cost_usd": round(cost, 6),
        "success": success,
        "error": error,
        "note": note,
    }

    with _lock:
        # 追加到 usage log
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        entries: List[Dict] = []
        if USAGE_FILE.exists():
            try:
                entries = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            except Exception:
                entries = []
        entries.append(record)
        # 只保留最近 10000 条，避免无限增长
        USAGE_FILE.write_text(
            json.dumps(entries[-10000:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 更新每日统计
        daily = _load_daily()
        day = _today()
        day_stat = daily.setdefault(day, {})
        prov_stat = day_stat.setdefault(provider, {"input": 0, "output": 0, "calls": 0})
        prov_stat["input"] += int(input_tokens)
        prov_stat["output"] += int(output_tokens)
        prov_stat["calls"] += 1
        _save_daily(daily)

    return record


def daily_usage(provider: str, date: str | None = None) -> Dict[str, int]:
    """查询某 provider 某天的用量（缺省今天）。"""
    day = date or _today()
    daily = _load_daily()
    return daily.get(day, {}).get(provider, {"input": 0, "output": 0, "calls": 0})


def is_over_limit(provider: str, daily_limit_input: int | None = None,
                  daily_limit_output: int | None = None) -> bool:
    """
    检查某 provider 是否已超过每日限额。
    limit 缺省读环境变量 {PROVIDER}_DAILY_LIMIT（总 token 数）。
    """
    usage = daily_usage(provider)
    total = usage["input"] + usage["output"]

    if daily_limit_input is not None and usage["input"] >= daily_limit_input:
        return True
    if daily_limit_output is not None and usage["output"] >= daily_limit_output:
        return True

    env_limit = os.environ.get(f"{provider.upper()}_DAILY_LIMIT", "")
    if env_limit:
        try:
            limit = int(env_limit)
            if total >= limit:
                return True
        except ValueError:
            pass
    return False


def _estimate_cost(provider: str, input_tokens: int, output_tokens: int) -> float:
    rates = _COST_PER_1K.get(provider, {"input": 0.0, "output": 0.0})
    return (input_tokens / 1000.0) * rates["input"] + (output_tokens / 1000.0) * rates["output"]


def get_cost_summary(provider: str | None = None, date: str | None = None) -> Dict:
    """汇总某天（缺省今天）的成本与调用次数。"""
    day = date or _today()
    daily = _load_daily()
    day_data = daily.get(day, {})
    providers = [provider] if provider else list(day_data.keys())
    summary = {"date": day, "total_calls": 0, "total_input": 0,
               "total_output": 0, "total_cost_usd": 0.0, "by_provider": {}}
    for p in providers:
        stat = day_data.get(p, {"input": 0, "output": 0, "calls": 0})
        cost = _estimate_cost(p, stat["input"], stat["output"])
        summary["total_calls"] += stat["calls"]
        summary["total_input"] += stat["input"]
        summary["total_output"] += stat["output"]
        summary["total_cost_usd"] += cost
        summary["by_provider"][p] = {**stat, "estimated_cost_usd": round(cost, 6)}
    summary["total_cost_usd"] = round(summary["total_cost_usd"], 6)
    return summary


def load_usage_log(limit: int = 500) -> List[Dict]:
    """读取最近 N 条调用日志（用于 Eval 分析）。"""
    if not USAGE_FILE.exists():
        return []
    try:
        entries = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        return entries[-limit:]
    except Exception:
        return []
