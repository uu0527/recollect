"""
ReCollect - 数据契约 (Schemas)
Phase 1: 仅定义数据结构，不包含业务逻辑
模块间通过 JSON/JSONL 文件通信，Schema 在此统一声明
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
import json


# ============================================================
# P1 Collect - 原始采集数据
# ============================================================
@dataclass
class RawNote:
    note_id: str
    url: str
    title: str
    content: str
    images: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | Dict) -> "RawNote":
        if isinstance(raw, str):
            raw = json.loads(raw)
        return cls(**raw)


# ============================================================
# P2 Screen - AI 筛选结果
# ============================================================
@dataclass
class ScreenedNote:
    note_id: str
    decision: str  # keep | review | drop
    ad_confidence: float  # 0.0 ~ 1.0
    is_ad: bool
    content_type: str  # 攻略 | 测评 | 教程 | 资讯 | 情绪 | 其他
    value_score: int  # 1 ~ 5
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | Dict) -> "ScreenedNote":
        if isinstance(raw, str):
            raw = json.loads(raw)
        return cls(**raw)


# ============================================================
# P3 Summary - AI 归纳结果
# ============================================================
@dataclass
class SummarizedNote:
    note_id: str
    title: str
    url: str
    category_l1: str
    category_l2: str
    tags: List[str]
    tldr: str
    key_points: List[str]
    actionable: str
    content_type: str  # 图文 | 视频
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, raw: str | Dict) -> "SummarizedNote":
        if isinstance(raw, str):
            raw = json.loads(raw)
        return cls(**raw)


# ============================================================
# P4 Write - 飞书写入记录
# ============================================================
@dataclass
class WriteRecord:
    note_id: str
    write_success: bool
    write_time: str
    target: str  # feishu | mock
    dedup_hit: bool = False
    error_msg: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


# ============================================================
# P5 Audit - 独立审计结果
# ============================================================
@dataclass
class AuditResult:
    note_id: str
    audit_score: float  # 综合分 0.0 ~ 1.0
    fidelity_score: float  # 保真度：是否符合原文
    coverage_score: float  # 覆盖度：是否遗漏重点
    category_score: float  # 分类正确
    comments: str
    audit_time: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_jsonl(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str | Dict) -> "AuditResult":
        if isinstance(raw, str):
            raw = json.loads(raw)
        return cls(**raw)


# ============================================================
# P6 Memory - 检索问答结果
# ============================================================
@dataclass
class RAGResult:
    query: str
    retrieved_note_ids: List[str]
    answer: str
    confidence: str  # high | medium | low
    retrieved_chunks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


# ============================================================
# 通用 IO 工具（仅文件读写，无业务逻辑）
# ============================================================
def load_jsonl(filepath: str, cls) -> List[Any]:
    """从 JSONL 加载对象列表"""
    results: List[Any] = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(cls.from_json(line))
    return results


def dump_jsonl(filepath: str, records: List[Any], mode: str = "w") -> None:
    """写入 JSONL (mode: w=覆盖, a=追加)"""
    with open(filepath, mode, encoding="utf-8") as f:
        for r in records:
            f.write(r.to_jsonl() + "\n")


def dump_json(filepath: str, records: List[Any]) -> None:
    """写入 JSON 数组（用于 P3 summary 等）"""
    data = [r.to_dict() for r in records]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_json(filepath: str, cls) -> List[Any]:
    """从 JSON 数组加载对象列表"""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [cls.from_json(item) for item in data]
