"""
Storage Adapter 单元测试
验证:
  1. File adapter 正常工作（add_event / list_events / upsert / get）
  2. Supabase adapter mock 工作（未配置 key 时降级 + 调用失败不阻断）
  3. knowledge upsert 幂等（同 note_id 覆盖）
  4. event 写入成功
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 用临时目录隔离文件 adapter 的输出
_TMP = Path(tempfile.mkdtemp(prefix="rc_storage_test_"))


def _patch_paths():
    import collector.context_store.adapters.file_adapter as fa
    fa.EVENTS_FILE = _TMP / "events" / "storage_events.jsonl"
    fa.KNOWLEDGE_FILE = _TMP / "01_raw" / "knowledge_cards.jsonl"


_patch_paths()

from collector.context_store.adapters import (  # noqa: E402
    FileStorageAdapter,
    get_adapter,
)
from collector.context_store.adapters import supabase_adapter  # noqa: E402


def _clean():
    for p in [_TMP / "events", _TMP / "01_raw"]:
        if p.exists():
            for f in p.glob("*.jsonl"):
                f.unlink()


def test_file_adapter_event_write():
    """File adapter: add_event 写入 + list_events 读取"""
    _clean()
    a = FileStorageAdapter()
    ev = {"event_type": "note_view", "note_id": "n1", "url": "u1",
          "title": "t1", "content": "c1", "images": [], "author": "a1",
          "timestamp": "2026-08-08T10:00:00"}
    ok = a.add_event(ev)
    assert ok, "add_event 应返回 True"
    # 重复写入（幂等）
    ok2 = a.add_event(ev)
    assert not ok2, "重复事件应返回 False（幂等）"
    events = a.list_events()
    assert len(events) == 1, f"应有 1 条事件, got {len(events)}"
    assert events[0]["note_id"] == "n1"
    print("PASS file_adapter event 写入+幂等+读取")


def test_file_adapter_knowledge_upsert_idempotent():
    """File adapter: knowledge upsert 幂等（同 note_id 覆盖）"""
    _clean()
    a = FileStorageAdapter()
    card1 = {"note_id": "k1", "title": "第一版", "tldr": "v1", "tags": ["a"]}
    card2 = {"note_id": "k1", "title": "第二版", "tldr": "v2", "tags": ["a", "b"]}
    a.upsert_knowledge(card1)
    a.upsert_knowledge(card2)  # 覆盖
    got = a.get_knowledge_by_note_id("k1")
    assert got is not None
    assert got["title"] == "第二版", f"应返回最新版, got {got['title']}"
    # 文件只有 1 条 k1
    rows = [json.loads(l) for l in
            (_TMP / "01_raw" / "knowledge_cards.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 1, f"k1 应只有 1 条, got {len(rows)}"
    assert got.get("updated_at"), "应有 updated_at"
    print("PASS file_adapter knowledge upsert 幂等覆盖")


def test_get_adapter_default_file():
    """默认（无环境变量）→ FileStorageAdapter"""
    os.environ.pop("STORAGE_BACKEND", None)
    a = get_adapter()
    assert isinstance(a, FileStorageAdapter)
    print("PASS get_adapter 默认 file")


def test_supabase_adapter_no_config_fallback():
    """Supabase adapter：无 key 配置 → 降级不抛错（返回 False/[]/None）"""
    os.environ["STORAGE_BACKEND"] = "supabase"
    os.environ.pop("SUPABASE_URL", None)
    os.environ.pop("SUPABASE_KEY", None)
    a = get_adapter()
    assert a.name == "supabase"
    # add_event 返回 False（client None）
    assert a.add_event({"note_id": "x"}) is False
    assert a.list_events() == []
    assert a.get_knowledge_by_note_id("x") is None
    print("PASS supabase 无配置降级不抛错")


def test_supabase_adapter_mock_call():
    """Supabase adapter：mock client 验证 upsert/insert 被调用"""
    os.environ["STORAGE_BACKEND"] = "supabase"
    os.environ["SUPABASE_URL"] = "https://mock.supabase.co"
    os.environ["SUPABASE_KEY"] = "mock-key"

    # mock create_client 返回 fake client
    fake_table = mock.MagicMock()
    fake_client = mock.MagicMock()
    fake_client.table.return_value = fake_table

    # upsert_knowledge
    with mock.patch.object(supabase_adapter, "_client", return_value=fake_client):
        fake_table.upsert.return_value.execute.return_value = mock.MagicMock()
        a = supabase_adapter.SupabaseStorageAdapter()
        ok = a.upsert_knowledge({"note_id": "k9", "title": "t", "tldr": "x"})
        assert ok is True
        fake_table.upsert.assert_called_once()
        _, kwargs = fake_table.upsert.call_args
        assert kwargs.get("on_conflict") == "note_id"

        # add_event：先查重（返回空 → 插入）
        fake_table.select.return_value = fake_table
        fake_table.eq.return_value = fake_table
        fake_table.limit.return_value = fake_table
        fake_table.execute.return_value = mock.MagicMock(data=[])
        fake_table.insert.return_value.execute.return_value = mock.MagicMock()
        ok2 = a.add_event({"event_type": "note_collect", "note_id": "n9"})
        assert ok2 is True
        fake_table.insert.assert_called_once()
    print("PASS supabase mock client upsert/insert 调用")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in fns:
        try:
            fn()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
        except Exception as e:
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n结果: {passed} 通过 / {len(fns) - passed} 失败")
    sys.exit(0 if passed == len(fns) else 1)
