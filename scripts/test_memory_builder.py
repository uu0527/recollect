"""
User Memory Builder 单元测试
覆盖: 主题聚合 / 行为加权 / 归一化 / 文件输出 / 缺失文件容错
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collector.memory_builder import (  # noqa: E402
    USER_MEMORY_FILE, build_user_memory, load_audit, load_events,
    load_summary, save_user_memory, update_user_memory,
)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _setup(tmp: Path):
    """构造 3 条 summary + audit + events"""
    summary_dir = tmp / "03_summary"
    audit_dir = tmp / "05_audit"
    events_dir = tmp / "events"
    summary_dir.mkdir(parents=True)
    audit_dir.mkdir(parents=True)
    events_dir.mkdir(parents=True)

    _write_json(summary_dir / "t1_summary.json", [
        {"note_id": "n1", "title": "AI Agent 入门", "category_l1": "技术趋势",
         "category_l2": "AI", "tags": ["LLM", "Agent", "产品"], "content_type": "图文"},
        {"note_id": "n2", "title": "AI 产品方法论", "category_l1": "技术趋势",
         "category_l2": "AI产品", "tags": ["AI", "产品"], "content_type": "图文"},
        {"note_id": "n3", "title": "上海落户指南", "category_l1": "城市生活",
         "category_l2": "落户", "tags": ["上海", "政策"], "content_type": "图文"},
    ])
    # audit: n1 高分, n2 中, n3 低
    _write_jsonl(audit_dir / "t1_audit.jsonl", [
        {"note_id": "n1", "audit_score": 0.9},
        {"note_id": "n2", "audit_score": 0.6},
        {"note_id": "n3", "audit_score": 0.3},
    ])
    # events: n1 收藏, n2 浏览, n3 浏览
    _write_jsonl(events_dir / "e1.jsonl", [
        {"event_type": "note_view", "note_id": "n1", "source": "browser"},
        {"event_type": "note_collect", "note_id": "n1", "source": "browser"},
        {"event_type": "note_view", "note_id": "n2", "source": "browser"},
        {"event_type": "note_view", "note_id": "n3", "source": "browser"},
    ])
    return summary_dir, audit_dir, events_dir


def test_build_topics_and_weighting():
    """主题聚合 + collect 行为加权"""
    with tempfile.TemporaryDirectory() as td:
        summary_dir, audit_dir, events_dir = _setup(Path(td))
        m = build_user_memory(summary_dir, audit_dir, events_dir, "t1")
        topics = {t["name"]: t for t in m["topics"]}
        assert "技术趋势" in topics  # n1+n2 聚合
        assert "城市生活" in topics
        # 技术趋势: n1(0.9*1.5) + n2(0.6*1.0) = 1.95 → 归一化 1.0
        # 城市生活: n3(0.3*1.0) = 0.3 → 归一化 0.15
        assert topics["技术趋势"]["interest_score"] == 1.0
        assert topics["城市生活"]["interest_score"] < 0.3
        assert topics["技术趋势"]["note_count"] == 2


def test_preferences_content_type():
    """内容偏好统计"""
    with tempfile.TemporaryDirectory() as td:
        summary_dir, audit_dir, events_dir = _setup(Path(td))
        m = build_user_memory(summary_dir, audit_dir, events_dir, "t1")
        assert "图文" in m["preferences"]["content_type"]


def test_save_and_update():
    """save_user_memory / update_user_memory 输出文件"""
    with tempfile.TemporaryDirectory() as td:
        summary_dir, audit_dir, events_dir = _setup(Path(td))
        out = Path(td) / "user_memory.json"
        memory = build_user_memory(summary_dir, audit_dir, events_dir, "t1")
        p = save_user_memory(memory, out)
        assert p.exists()
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        assert "topics" in d and "updated_at" in d

        # update 走默认路径（临时改 USER_MEMORY_FILE 用 monkeypatch 语义）
        import collector.memory_builder as mb
        orig = mb.USER_MEMORY_FILE
        mb.USER_MEMORY_FILE = Path(td) / "default_user_memory.json"
        try:
            m = update_user_memory(summary_dir, audit_dir, events_dir, "t1")
            assert m["stats"]["notes_processed"] == 3
            assert mb.USER_MEMORY_FILE.exists()
        finally:
            mb.USER_MEMORY_FILE = orig


def test_missing_files():
    """summary/audit/events 缺失 → 空结果不报错"""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "03_summary").mkdir(parents=True)
        m = build_user_memory(d / "03_summary", d / "05_audit", d / "events", "none")
        assert m["topics"] == []
        assert m["stats"]["notes_processed"] == 0


def test_load_functions():
    """读取函数容错"""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        assert load_summary(d, "x") == []
        assert load_audit(d, "x") == {}
        assert load_events(d) == {}


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
