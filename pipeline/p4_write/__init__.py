"""
P4 飞书写入模块 - Mock 实现（Phase 2）
- use_mock=True（默认）：写入本地 JSONL 模拟 Bitable 主库，支持 note_id 去重
- use_mock=False：占位（预留真实 Feishu API）
- 写入 Gate：仅写入审计通过（audit_score >= min_audit_score）或未审计（only_audited=False）的 note
- 写入后**同步调用 P6.build_index(incremental=True)**（P6 索引前置：随写随建）
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from schemas import (
    SummarizedNote, AuditResult, WriteRecord,
    load_json, load_jsonl, dump_jsonl,
)
from config import (
    path_summary, path_audit, path_write_record,
    FEISHU, WRITE_DIR,
)


# ============================================================
# Mock Feishu Bitable：读写本地 JSONL + 内存去重
# ============================================================
class MockBitable:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def load_existing_ids(self) -> Set[str]:
        ids: Set[str] = set()
        if not self.path.exists():
            return ids
        with open(self.path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rec = json.loads(ln)
                    if "note_id" in rec:
                        ids.add(rec["note_id"])
                except Exception:
                    pass
        return ids

    def append_rows(self, rows: List[Dict]) -> None:
        with open(self.path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _row_mapping(s: SummarizedNote, audit: Optional[AuditResult]) -> Dict:
    """字段 mapping：SummarizedNote + Audit → 飞书 Bitable 一行"""
    return {
        "note_id": s.note_id,
        "标题": s.title,
        "链接": s.url,
        "一级分类": s.category_l1,
        "二级分类": s.category_l2,
        "标签": ",".join(s.tags),
        "TLDR": s.tldr,
        "要点": "\n".join(f"- {k}" for k in s.key_points),
        "可执行建议": s.actionable,
        "来源类型": s.content_type,
        "收藏时间": s.note_id,  # 占位
        "状态": "keep",
        "审计分": round(audit.audit_score, 3) if audit else "",
        "入库时间": datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================
# 公共入口
# ============================================================
def run(task_id: str,
        use_mock: Optional[bool] = None,
        only_audited: bool = True,
        min_audit_score: float = 0.6,
        **kwargs) -> Path:
    mock = FEISHU["use_mock"] if use_mock is None else use_mock
    summaries: List[SummarizedNote] = load_json(str(path_summary(task_id)), SummarizedNote)
    audits: List[AuditResult] = (
        load_jsonl(str(path_audit(task_id)), AuditResult) if path_audit(task_id).exists() else []
    )
    audit_map: Dict[str, AuditResult] = {a.note_id: a for a in audits}

    # Gate：决定哪些 summary 可以写入
    writable: List[tuple[SummarizedNote, Optional[AuditResult]]] = []
    for s in summaries:
        aud = audit_map.get(s.note_id)
        if only_audited and aud is None:
            continue
        if aud is not None and aud.audit_score < min_audit_score:
            continue
        writable.append((s, aud))

    # 写入 Mock Bitable（去重）
    records: List[WriteRecord] = []
    existing_ids: Set[str] = set()
    if mock:
        mb = MockBitable(Path(FEISHU["mock_output"]))
        existing_ids = mb.load_existing_ids()
        rows_to_append: List[Dict] = []
        for s, aud in writable:
            if s.note_id in existing_ids:
                records.append(WriteRecord(
                    note_id=s.note_id, write_success=True,
                    write_time=datetime.now().isoformat(timespec="seconds"),
                    target="mock", dedup_hit=True,
                ))
                continue
            rows_to_append.append(_row_mapping(s, aud))
            existing_ids.add(s.note_id)
            records.append(WriteRecord(
                note_id=s.note_id, write_success=True,
                write_time=datetime.now().isoformat(timespec="seconds"),
                target="mock", dedup_hit=False,
            ))
        mb.append_rows(rows_to_append)
        wrote = len(rows_to_append)
    else:
        # 真实 Feishu：Phase 2 不实现
        for s, aud in writable:
            records.append(WriteRecord(
                note_id=s.note_id, write_success=False,
                write_time=datetime.now().isoformat(timespec="seconds"),
                target="feishu",
                error_msg="真实飞书未接入（仅 mock）",
            ))
        wrote = 0

    # 写后回读校验：检查 mock 文件中的 note_id 是否都在
    if mock and wrote:
        mb_after = MockBitable(Path(FEISHU["mock_output"]))
        now_ids = mb_after.load_existing_ids()
        missing = [s.note_id for s, _ in writable if s.note_id not in now_ids]
        if missing:
            for r in records:
                if r.note_id in missing:
                    r.write_success = False
                    r.error_msg = "写后回读校验失败（未找到 note_id）"

    record_path = path_write_record(task_id)
    dump_jsonl(str(record_path), records, mode="w")

    # === P6 索引前置：写入完成 → 增量建 embedding 索引 ===
    try:
        from pipeline.p6_memory import build_index
        build_index(task_id, incremental=True)
    except NotImplementedError:
        pass
    except Exception as e:
        print(f"[P4→P6] 增量索引失败（非致命）: {e!r}")

    dedup_cnt = sum(1 for r in records if r.dedup_hit)
    fail_cnt = sum(1 for r in records if not r.write_success)
    print(f"[P4] task_id={task_id}  写入 target={'mock' if mock else 'feishu'}  "
          f"通过{len(writable)}条  实际写入{wrote}条  去重命中{dedup_cnt}条  失败{fail_cnt}条  "
          f"→ {record_path.name}")
    return record_path
