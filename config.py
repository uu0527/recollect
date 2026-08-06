"""
ReCollect - 全局配置
Phase 1: 仅定义路径、常量和阈值，无业务逻辑
"""
from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv() ============================================================
# 根路径
# ============================================================
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = BASE_DIR / "data"
PIPELINE_DIR: Path = BASE_DIR / "pipeline"
MEMORY_DIR: Path = BASE_DIR / "memory"
EVAL_DIR: Path = MEMORY_DIR / "eval"
FRONTEND_DIR: Path = BASE_DIR / "frontend"
SCRIPTS_DIR: Path = BASE_DIR / "scripts"

# ============================================================
# 数据阶段目录（按 P1~P6 契约）
# ============================================================
RAW_DIR: Path = DATA_DIR / "01_raw"
SCREENED_DIR: Path = DATA_DIR / "02_screened"
SUMMARY_DIR: Path = DATA_DIR / "03_summary"
WRITE_DIR: Path = DATA_DIR / "04_write"
AUDIT_DIR: Path = DATA_DIR / "05_audit"
MEMORY_DATA_DIR: Path = DATA_DIR / "06_memory"
CHROMA_INDEX_DIR: Path = MEMORY_DATA_DIR / "chroma_index"

# 确保所有目录存在
for _d in [
    DATA_DIR, RAW_DIR, SCREENED_DIR, SUMMARY_DIR, WRITE_DIR,
    AUDIT_DIR, MEMORY_DATA_DIR, CHROMA_INDEX_DIR,
    EVAL_DIR, FRONTEND_DIR, SCRIPTS_DIR,
]:
    _d.mkdir(parents=True, exist_ok=True)

# ============================================================
# 阶段文件名生成（按 task_id 前缀，支持幂等重跑）
# ============================================================
def path_raw(task_id: str) -> Path:
    return RAW_DIR / f"{task_id}_notes.jsonl"

def path_screened(task_id: str) -> Path:
    return SCREENED_DIR / f"{task_id}_screened.jsonl"

def path_summary(task_id: str) -> Path:
    return SUMMARY_DIR / f"{task_id}_summary.json"

def path_write_record(task_id: str) -> Path:
    return WRITE_DIR / f"{task_id}_write_records.jsonl"

def path_audit(task_id: str) -> Path:
    return AUDIT_DIR / f"{task_id}_audit.jsonl"

def path_chroma(task_id: str) -> Path:
    return CHROMA_INDEX_DIR / task_id

def path_rag_result(task_id: str, query_id: str = "q1") -> Path:
    return MEMORY_DATA_DIR / f"{task_id}_rag_{query_id}.json"

# ============================================================
# P2 筛选阈值（可通过配置调整）
# ============================================================
P2_THRESHOLDS = {
    "ad_drop": 0.85,       # ad_confidence >= 0.85  → drop
    "ad_review_low": 0.3,  # ad_confidence < 0.3
    "value_keep_min": 3,   # value_score >= 3
}

# ============================================================
# P4 飞书配置（默认使用 mock adapter，真实环境配环境变量）
# ============================================================
FEISHU = {
    "use_mock": True,
    "mock_output": WRITE_DIR / "mock_feishu_bitable.jsonl",
    "app_id": os.environ.get("FEISHU_APP_ID", ""),
    "app_secret": os.environ.get("FEISHU_APP_SECRET", ""),
    "bitable_app_token": os.environ.get("FEISHU_BITABLE_TOKEN", ""),
    "bitable_table_id": os.environ.get("FEISHU_BITABLE_TABLE_ID", ""),
}

# ============================================================
# P6 RAG 配置
# ============================================================
RAG = {
    "top_k": 5,
    "embedding_dim": 384,  # bge-small 维度
}

# ============================================================
# 全链路阶段依赖顺序
# ============================================================
STAGE_ORDER = ["p1", "p2", "p3", "p5", "p4", "p6"]

# ============================================================
# LLM Provider 配置（Phase 3）
# provider 可选: mock / openai / kimi / deepseek
# 切换真实模型只需改 provider 字段，api_key 从环境变量读取
# ============================================================
MODEL_CONFIG: dict = {
    # 全局默认
    "default": "mock",
    "timeout": 30,
    "max_retries": 3,
    "temperature": 0.0,

    # 各阶段 per-stage 覆盖（provider + temperature）
    "p2": {
        "provider": os.environ.get("RECOLLECT_P2_PROVIDER", "mock"),
        "temperature": 0.0,   # 分类任务：确定性输出
    },
    "p3": {
        "provider": os.environ.get("RECOLLECT_P3_PROVIDER", "mock"),
        "temperature": 0.3,   # 归纳任务：允许少量创造性
    },
    "p5": {
        "provider": os.environ.get("RECOLLECT_P5_PROVIDER", "mock"),
        "temperature": 0.0,   # 审计任务：确定性输出；实例必须与 P3 隔离
    },
    "p6": {
        "provider": os.environ.get("RECOLLECT_P6_PROVIDER", "mock"),
        "temperature": 0.3,
    },

    # 各 provider API key（从环境变量读取，不硬编码）
    "openai_api_key":   os.environ.get("OPENAI_API_KEY", ""),
    "kimi_api_key":     os.environ.get("KIMI_API_KEY", ""),
    "deepseek_api_key": os.environ.get("DEEPSEEK_API_KEY", 
    "qwen_api_key":     os.environ.get("QWEN_API_KEY", "sk-ff94ea2ed9884d539b258db9efa973ee")
""),

    # 可选：指定具体 model 名称（不填则用 provider 默认）
    "openai_model":    os.environ.get("OPENAI_MODEL", ""),
    "kimi_model":      os.environ.get("KIMI_MODEL", ""),
    "deepseek_model":  os.environ.get("DEEPSEEK_MODEL", ""),
}
