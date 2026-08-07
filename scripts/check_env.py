#!/usr/bin/env python3
"""
ReCollect 环境配置自检

用法：
    python scripts/check_env.py

输出：当前启用的 Provider / 各 API 配置状态 / Feishu 状态 / 当前模式。
不打印任何 API Key 内容，仅显示是否已配置。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path（支持从任意 cwd 运行）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 加载 .env（与 config.py 一致）
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

# ============================================================
# 检查项定义
# ============================================================
PROVIDERS = {
    "P2": os.environ.get("RECOLLECT_P2_PROVIDER", "").strip() or "未设置",
    "P3": os.environ.get("RECOLLECT_P3_PROVIDER", "").strip() or "未设置",
    "P5": os.environ.get("RECOLLECT_P5_PROVIDER", "").strip() or "未设置",
    "P6": os.environ.get("RECOLLECT_P6_PROVIDER", "").strip() or "未设置",
}

API_KEYS = {
    "DeepSeek": "DEEPSEEK_API_KEY",
    "Qwen": "QWEN_API_KEY",
    "Zhipu": "ZHIPU_API_KEY",
    "OpenAI(预留)": "OPENAI_API_KEY",
    "Kimi(预留)": "KIMI_API_KEY",
    "Qwen Vision": "DASHSCOPE_API_KEY",
}

FEISHU_KEYS = {
    "Feishu App ID": "FEISHU_APP_ID",
    "Feishu App Secret": "FEISHU_APP_SECRET",
    "Bitable Token": "FEISHU_BITABLE_TOKEN",
    "Bitable Table ID": "FEISHU_BITABLE_TABLE_ID",
}

MOCK = "mock"


def is_set(name: str) -> bool:
    """变量是否已配置（非空且非占位符）"""
    v = os.environ.get(name, "").strip()
    if not v:
        return False
    if v.lower() in {"你的key", "your-key", "your_key", "xxx", "sk-xxx", "todo"}:
        return False
    return True


def provider_ok(name: str) -> bool:
    """Provider 是否有效（mock 恒有效；其余需对应 key 已配置）"""
    prov = os.environ.get(name, "").strip()
    if not prov or prov == MOCK:
        return True
    key_env = {
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "QWEN_API_KEY",
        "zhipu": "ZHIPU_API_KEY",
        "openai": "OPENAI_API_KEY",
        "kimi": "KIMI_API_KEY",
    }.get(prov)
    return bool(key_env and is_set(key_env))


# ============================================================
# 输出
# ============================================================
def main() -> int:
    missing_any = False
    line = "=" * 44

    print(line)
    print("ReCollect Environment Check")
    print(line)

    # 1. Provider
    print("\n-- Provider --")
    for stage, prov in PROVIDERS.items():
        ok = provider_ok(f"RECOLLECT_{stage}_PROVIDER")
        mark = "OK" if ok else "INVALID"
        if not ok:
            missing_any = True
        print(f"{stage} Provider : {prov:<12} [{mark}]")

    # 2. API Keys
    print("\n-- API Keys --")
    for label, env in API_KEYS.items():
        status = "Configured" if is_set(env) else "Missing"
        if not is_set(env):
            missing_any = True
        print(f"{label:<14} : {status}")

    # 3. Feishu
    print("\n-- Feishu --")
    feishu_complete = True
    for label, env in FEISHU_KEYS.items():
        status = "Configured" if is_set(env) else "Missing"
        if not is_set(env):
            feishu_complete = False
            missing_any = True
        print(f"{label:<17} : {status}")

    # 4. 当前模式
    print("\n-- Current Mode --")
    if feishu_complete:
        mode = "Real (P4 真实写库)"
    else:
        mode = "Mock (P4 自动降级)"
    print(f"P4 Write Mode  : {mode}")

    # 5. .env 是否存在
    env_file = ROOT / ".env"
    if not env_file.exists():
        print("\n[WARN] .env 不存在，请复制 .env.example 为 .env 并填写")
        missing_any = True

    print()
    print(line)
    if missing_any:
        print("Result: 部分配置缺失（不影响启动，缺失项对应功能降级）")
        print("提示: 复制 .env.example → .env，或参考 README《环境配置》章节")
    else:
        print("Result: 环境配置完整")
    print(line)
    return 0 if not missing_any else 1


if __name__ == "__main__":
    sys.exit(main())
