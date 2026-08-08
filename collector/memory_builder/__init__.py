"""
User Memory Builder（Memory Layer MVP）

职责：
  从一次 pipeline 运行的产物（summary / audit / events）中
  提取用户兴趣信号，生成/更新用户长期记忆文件：
    data/06_memory/user_memory.json

输入：
  - data/03_summary/{task}_summary.json  （内容：category/tags/content_type）
  - data/05_audit/{task}_audit.jsonl     （质量：audit_score）
  - data/events/*.jsonl                  （行为：note_view/note_collect 时间线）

输出：
  data/06_memory/user_memory.json
  {
    "topics": [
      {"name": "AI产品经理", "interest_score": 0.8,
       "evidence": ["收藏AI Agent相关内容", "多次阅读LLM产品文章"]}
    ],
    "preferences": {"content_type": ["技术趋势", "产品方法论"]},
    "updated_at": "..."
  }

原则：
  - 不修改采集链路 / P2-P6 / event_router / resolver
  - 纯统计 + 简单启发式（不引入数据库 / 不接 LLM）
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

USER_MEMORY_FILE = ROOT / "data" / "06_memory" / "user_memory.json"


# ============================================================
# 读取
# ============================================================
def load_summary(summary_dir: Path, task_id: str) -> List[Dict]:
    """读取 {task}_summary.json（list of SummarizedNote）"""
    p = summary_dir / f"{task_id}_summary.json"
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else [data]


def load_audit(audit_dir: Path, task_id: str) -> Dict[str, float]:
    """读取 {task}_audit.jsonl → note_id → audit_score"""
    p = audit_dir / f"{task_id}_audit.jsonl"
    result: Dict[str, float] = {}
    if not p.exists():
        return result
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if d.get("note_id") and d.get("audit_score") is not None:
            result[d["note_id"]] = float(d["audit_score"])
    return result


def load_events(events_dir: Path) -> Dict[str, List[str]]:
    """读取事件时间线 → note_id → 行为列表（view/collect）"""
    result: Dict[str, List[str]] = defaultdict(list)
    if not events_dir.exists():
        return dict(result)
    for f in sorted(events_dir.glob("*.jsonl")):
        if f.name.startswith("pending_"):
            continue
        try:
            for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                nid = d.get("note_id")
                etype = d.get("event_type")
                if nid and etype in ("note_view", "note_collect"):
                    result[nid].append(etype)
        except OSError:
            continue
    return dict(result)


# ============================================================
# 记忆构建
# ============================================================
def build_user_memory(summary_dir: Path, audit_dir: Path,
                      events_dir: Path, task_id: str) -> Dict:
    """构建用户记忆（主题兴趣 + 内容偏好）"""
    notes = load_summary(summary_dir, task_id)
    audit = load_audit(audit_dir, task_id)
    behaviors = load_events(events_dir)

    # --- 主题聚合：category_l1 为一级主题 ---
    topic_scores: Dict[str, Dict] = defaultdict(
        lambda: {"score": 0.0, "evidence": [], "notes": 0}
    )
    content_types = Counter()

    for n in notes:
        nid = n.get("note_id", "")
        l1 = n.get("category_l1", "") or "未分类"
        l2 = n.get("category_l2", "") or ""
        tags = n.get("tags", []) or []
        ct = n.get("content_type", "") or "图文"
        content_types[ct] += 1

        # 质量权重：audit_score（默认 0.5）
        q = audit.get(nid, 0.5)
        # 行为权重：collect(收藏) > view(浏览)
        acts = behaviors.get(nid, [])
        behavior_w = 1.5 if "note_collect" in acts else 1.0
        # 信号分 = 质量 × 行为权重
        signal = q * behavior_w

        # 一级主题
        t = topic_scores[l1]
        t["score"] += signal
        t["notes"] += 1
        if l2:
            t["evidence"].append(f"关注{l2}")
        for tag in tags[:3]:
            t["evidence"].append(f"收藏#{tag}")

    # --- 生成 topics（归一化到 0~1）---
    max_score = max((v["score"] for v in topic_scores.values()), default=1.0)
    topics = []
    for name, t in sorted(topic_scores.items(), key=lambda x: -x[1]["score"]):
        topics.append({
            "name": name,
            "interest_score": round(min(1.0, t["score"] / max(1.0, max_score)), 2),
            "evidence": t["evidence"][:4],
            "note_count": t["notes"],
        })

    # --- 内容偏好 ---
    preferences = {
        "content_type": [ct for ct, _ in content_types.most_common(3)],
    }

    return {
        "topics": topics,
        "preferences": preferences,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": {
            "notes_processed": len(notes),
            "collect_count": sum(1 for acts in behaviors.values() if "note_collect" in acts),
            "view_count": sum(1 for acts in behaviors.values() if "note_view" in acts),
        },
    }


def save_user_memory(memory: Dict, out_file: Path | None = None) -> Path:
    """写入 user_memory.json"""
    p = out_file or USER_MEMORY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)
    return p


def update_user_memory(summary_dir: Path, audit_dir: Path,
                       events_dir: Path, task_id: str) -> Dict:
    """完整流程：构建 + 保存 + 返回"""
    memory = build_user_memory(summary_dir, audit_dir, events_dir, task_id)
    save_user_memory(memory)
    print(f"[Memory] updated user profile ({memory['stats']['notes_processed']} notes, "
          f"{len(memory['topics'])} topics)")
    return memory
