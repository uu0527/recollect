"""
Mock Feishu Writer Adapter 单元测试
覆盖: 成功行转换 / 失败行跳过 / 字段映射 / summary 缺失 / 文件不存在
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.feishu_adapter.mock_writer import (  # noqa: E402
    OUT_FILE_NAME, build_mock_bitable, load_write_records, load_summary,
    to_bitable_row,
)


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def test_to_bitable_row_full_mapping():
    """完整字段映射"""
    record = {"note_id": "n1", "write_success": True, "write_time": "2026-08-08T10:00:00"}
    summary = {
        "note_id": "n1",
        "title": "测试标题",
        "category_l1": "生活方式",
        "category_l2": "养宠",
        "tags": ["猫", "健康"],
        "tldr": "这是一段摘要",
        "url": "https://xhs.com/explore/n1",
    }
    row = to_bitable_row(record, {summary["note_id"]: summary})
    assert row["title"] == "测试标题"
    assert row["category"] == "生活方式"  # category_l1 优先
    assert row["tags"] == ["猫", "健康"]
    assert row["summary"] == "这是一段摘要"
    assert row["source_url"] == "https://xhs.com/explore/n1"
    assert row["created_at"] == "2026-08-08T10:00:00"


def test_to_bitable_row_category_fallback():
    """category_l1 缺失 → 用 category_l2"""
    record = {"note_id": "n2", "write_success": True, "write_time": "t"}
    summary = {"note_id": "n2", "title": "t", "category_l2": "科学养宠", "tldr": "s", "url": "u"}
    row = to_bitable_row(record, {summary["note_id"]: summary})
    assert row["category"] == "科学养宠"


def test_build_mock_bitable_success_and_skip():
    """成功行转换 + 失败行跳过 + 输出文件生成"""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        write_dir = d / "04_write"
        summary_dir = d / "03_summary"
        write_dir.mkdir(parents=True)
        summary_dir.mkdir(parents=True)

        # write_records: 1 成功 + 1 失败
        _write_jsonl(write_dir / "t1_write_records.jsonl", [
            {"note_id": "n1", "write_success": True, "write_time": "2026-08-08T10:00:00", "target": "feishu"},
            {"note_id": "n2", "write_success": False, "write_time": "2026-08-08T10:01:00", "target": "feishu", "error_msg": "api 404"},
        ])
        # summary: 只有 n1
        _write_json(summary_dir / "t1_summary.json", [
            {"note_id": "n1", "title": "笔记一", "category_l1": "资讯", "tags": ["a"], "tldr": "摘要一", "url": "u1"},
        ])

        rows = build_mock_bitable(write_dir, summary_dir, "t1")

        assert len(rows) == 1  # 失败行被跳过
        assert rows[0]["title"] == "笔记一"

        out = write_dir / OUT_FILE_NAME
        assert out.exists()
        lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) == 1
        assert json.loads(lines[0])["title"] == "笔记一"


def test_build_mock_bitable_missing_summary():
    """summary 缺失 → 表行字段为空但不报错"""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        write_dir = d / "04_write"
        summary_dir = d / "03_summary"
        write_dir.mkdir(parents=True)
        summary_dir.mkdir(parents=True)

        _write_jsonl(write_dir / "t2_write_records.jsonl", [
            {"note_id": "n9", "write_success": True, "write_time": "t"},
        ])
        # 不写 summary 文件
        rows = build_mock_bitable(write_dir, summary_dir, "t2")
        assert len(rows) == 1
        assert rows[0]["title"] == ""
        assert rows[0]["summary"] == ""


def test_load_write_records_file_missing():
    """write_records 文件不存在 → 空列表不报错"""
    with tempfile.TemporaryDirectory() as td:
        assert load_write_records(Path(td), "nonexistent") == []


def test_load_summary_file_missing():
    """summary 文件不存在 → 空 dict 不报错"""
    with tempfile.TemporaryDirectory() as td:
        assert load_summary(Path(td), "nonexistent") == {}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n结果: {passed} 通过 / {len(fns) - passed} 失败")
    sys.exit(0 if passed == len(fns) else 1)
