"""
P4 飞书写入模块 - Mock 实现（Phase 2）
- use_mock=True（默认）：写入本地 JSONL 模拟 Bitable 主库，支持 note_id 去重
- use_mock=False：占位（预留真实 Feishu API）
- 写入 Gate：仅写入审计通过（audit_score >= min_audit_score）或未审计（only_audited=False）的 note
- 写入后**同步调用 P6.build_index(incremental=True)**（P6 索引前置：随写随建）
"""
from __future__ import annotations

import json
import time
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

# lark-oapi SDK
try:
    from lark_oapi import ApiClient, Config, LogLevel, RetryConfig
    from lark_oapi.api.bitable.v1 import *
except ImportError:
    # 如果未安装，mock 模式仍可工作
    pass


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
        # 飞书 URL 字段(type=15) 要求 {text, link} 对象格式
        "链接": {"text": s.url, "link": s.url} if s.url else "",
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
# Feishu Bitable：真实飞书 API 封装（Phase 3）
# ============================================================
class FeishuBitable:
    """
    真实飞书 Bitable 写入（HTTP 直连，不依赖 lark-oapi SDK 版本差异）
    - 懒获取 tenant_access_token
    - 批量 upsert：先搜索 note_id → 存在则更新，否则创建
    - 错误重试（指数退避）
    """

    API_BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str, app_secret: str, bitable_app_token: str, bitable_table_id: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.bitable_app_token = bitable_app_token
        self.bitable_table_id = bitable_table_id
        self._token: Optional[str] = None

    # ------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------
    def _get_token(self) -> str:
        if self._token:
            return self._token
        body = {"app_id": self.app_id, "app_secret": self.app_secret}
        resp = self._post(f"{self.API_BASE}/auth/v3/tenant_access_token/internal", body)
        if resp.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {resp.get('msg')}")
        self._token = resp["tenant_access_token"]
        return self._token

    # ------------------------------------------------------------
    # HTTP 工具
    # ------------------------------------------------------------
    @staticmethod
    def _post(url: str, body: Dict, token: str = "") -> Dict:
        import json as _json
        import urllib.request

        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(
            url, data=_json.dumps(body).encode("utf-8"), method="POST", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def _get(url: str, token: str) -> Dict:
        import json as _json
        import urllib.request

        req = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    # ------------------------------------------------------------
    # 记录操作
    # ------------------------------------------------------------
    def _create_record(self, record: Dict) -> bool:
        """创建单条记录，失败返回 False"""
        try:
            resp = self._post(
                f"{self.API_BASE}/bitable/v1/apps/{self.bitable_app_token}/tables/{self.bitable_table_id}/records",
                {"fields": record},
                self._get_token(),
            )
            return resp.get("code") == 0
        except Exception as e:
            print(f"[FeishuBitable] create_record 失败: {e!r}")
            return False

    def _batch_upsert_records(self, records: List[Dict], key_field: str = "note_id") -> int:
        """
        批量 upsert 记录（先查后建/更新）
        - records: List[Dict]，每条是 _row_mapping 的结果
        - key_field: 用于去重的字段名（默认 "note_id"）
        返回：成功写入数量
        """
        import urllib.parse

        token = self._get_token()
        success_cnt = 0
        for record in records:
            try:
                # 先尝试查询是否存在（飞书标准 filter 语法）
                if key_field in record:
                    filter_expr = f'CurrentValue.[{key_field}]="{record[key_field]}"'
                    query = urllib.parse.urlencode({"filter": filter_expr, "page_size": 1})
                    resp = self._get(
                        f"{self.API_BASE}/bitable/v1/apps/{self.bitable_app_token}/tables/{self.bitable_table_id}/records?{query}",
                        token,
                    )
                    items = (resp.get("data") or {}).get("items") or []
                    if resp.get("code") == 0 and items:
                        # 存在：更新
                        record_id = items[0].get("record_id")
                        upd = self._post(
                            f"{self.API_BASE}/bitable/v1/apps/{self.bitable_app_token}/tables/{self.bitable_table_id}/records/{record_id}",
                            {"fields": record},
                            token,
                        )
                        if upd.get("code") == 0:
                            success_cnt += 1
                        continue
                # 不存在：创建
                if self._create_record(record):
                    success_cnt += 1
            except Exception as e:
                print(f"[FeishuBitable] batch_upsert_records 单条失败: {e!r}")
                continue
        return success_cnt

    def upsert_rows(self, rows: List[Dict]) -> int:
        """批量 upsert，带指数退避重试"""
        last_exc = None
        for attempt in range(3):  # 最多重试 3 次
            try:
                return self._batch_upsert_records(rows)
            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                print(f"[FeishuBitable] upsert_rows 尝试 {attempt + 1}/3 失败，等待 {wait}s: {exc!r}")
                time.sleep(wait)
        raise RuntimeError(f"[FeishuBitable] upsert_rows 重试 3 次全部失败: {last_exc}")


# ============================================================
# Digest 文档生成（周报 / 汇总展示层）
# ============================================================
def generate_digest(task_id: str, written_notes: List[tuple[SummarizedNote, Optional[AuditResult]]],
                    digest_path: Optional[Path] = None) -> Path:
    """
    生成 digest Markdown：汇总本周入库的知识卡片。
    输出：data/04_write/{task_id}_digest.md
    用途：飞书 Wiki 展示层 / 周报 / demo 演示
    """
    if digest_path is None:
        digest_path = WRITE_DIR / f"{task_id}_digest.md"

    now = datetime.now()
    lines = [
        f"# ReCollect 知识周报 · {now.strftime('%Y-%m-%d')}",
        "",
        f"> 本次入库 **{len(written_notes)}** 条收藏，已自动整理为可检索知识卡片。",
        "",
        "---",
        "",
    ]

    # 按一级分类分组
    by_cat: Dict[str, List] = {}
    for s, aud in written_notes:
        by_cat.setdefault(s.category_l1, []).append((s, aud))

    for l1 in sorted(by_cat.keys()):
        items = by_cat[l1]
        lines.append(f"## {l1}（{len(items)} 条）")
        lines.append("")
        for s, aud in items:
            score = f" ｜审计分 {aud.audit_score:.2f}" if aud else ""
            lines.append(f"### {s.title}")
            lines.append("")
            lines.append(f"- 链接：{s.url}")
            lines.append(f"- 分类：{s.category_l1} / {s.category_l2}")
            lines.append(f"- 标签：{', '.join(s.tags)}{score}")
            lines.append("")
            lines.append(f"> **TLDR**：{s.tldr}")
            lines.append("")
            lines.append("要点：")
            for kp in s.key_points:
                lines.append(f"- {kp}")
            lines.append("")
            if s.actionable:
                lines.append(f"**可执行建议**：{s.actionable}")
                lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("> 本 digest 由 ReCollect 自动生成，点击链接可回看原文。")
    digest_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[P4→digest] {digest_path.name} 已生成（{len(written_notes)} 条）")
    return digest_path


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

    # 写入 Bitable（mock 或真实）
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
        # 真实 Feishu：Phase 3 实现
        app_id = FEISHU.get("app_id")
        app_secret = FEISHU.get("app_secret")
        bitable_app_token = FEISHU.get("bitable_app_token")
        bitable_table_id = FEISHU.get("bitable_table_id")
        if not all([app_id, app_secret, bitable_app_token, bitable_table_id]):
            print(f"[P4] 缺少飞书配置，请检查 FEISHU 环境变量或 config.py。回退到 mock。")
            mock = True
            mb = MockBitable(Path(FEISHU["mock_output"]))
            existing_ids = mb.load_existing_ids()
            rows_to_append: List[Dict] = []
            for s, aud in writable:
                if s.note_id in existing_ids:
                    records.append(WriteRecord(
                        note_id=s.note_id, write_success=True,
                        write_time=datetime.now().isoformat(timespec="seconds"),
                        target="feishu", dedup_hit=True,
                    ))
                    continue
                rows_to_append.append(_row_mapping(s, aud))
                existing_ids.add(s.note_id)
                records.append(WriteRecord(
                    note_id=s.note_id, write_success=True,
                    write_time=datetime.now().isoformat(timespec="seconds"),
                    target="feishu", dedup_hit=False,
                ))
            mb.append_rows(rows_to_append)
            wrote = len(rows_to_append)
        else:
            try:
                feishu = FeishuBitable(app_id, app_secret, bitable_app_token, bitable_table_id)
                rows_to_upsert = [_row_mapping(s, aud) for s, aud in writable]
                wrote = feishu.upsert_rows(rows_to_upsert)
                for s, aud in writable:
                    records.append(WriteRecord(
                        note_id=s.note_id, write_success=True,
                        write_time=datetime.now().isoformat(timespec="seconds"),
                        target="feishu", dedup_hit=False,
                    ))
            except Exception as exc:
                print(f"[P4] 真实飞书写入失败，回退 mock: {exc!r}")
                mock = True
                mb = MockBitable(Path(FEISHU["mock_output"]))
                existing_ids = mb.load_existing_ids()
                rows_to_append: List[Dict] = []
                for s, aud in writable:
                    if s.note_id in existing_ids:
                        records.append(WriteRecord(
                            note_id=s.note_id, write_success=True,
                            write_time=datetime.now().isoformat(timespec="seconds"),
                            target="feishu", dedup_hit=True,
                        ))
                        continue
                    rows_to_append.append(_row_mapping(s, aud))
                    existing_ids.add(s.note_id)
                    records.append(WriteRecord(
                        note_id=s.note_id, write_success=True,
                        write_time=datetime.now().isoformat(timespec="seconds"),
                        target="feishu", dedup_hit=False,
                    ))
                mb.append_rows(rows_to_append)
                wrote = len(rows_to_append)

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

    # === Digest 文档生成（实际写入的笔记汇总）===
    try:
        written_notes = [t for t in writable if t[0].note_id in
                         {r.note_id for r in records if r.write_success and not r.dedup_hit}]
        if written_notes:
            generate_digest(task_id, written_notes)
    except Exception as e:
        print(f"[P4→digest] digest 生成失败（非致命）: {e!r}")

    return record_path
