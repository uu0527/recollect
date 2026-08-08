# ReCollect MVP E2E 验证记录

- **日期**: 2026-08-08
- **版本**: v0.2.10 + Phase 2 + Memory Layer MVP
- **范围**: 用户收藏行为 → 知识卡片 → 用户记忆 完整闭环

---

## 测试目标

用户收藏小红书笔记后，系统自动完成：
1. 采集（note_view / note_collect 事件）
2. 解析（event_router → pending → resolver）
3. 处理（P2 筛选 → P3 总结 → P4 写入）
4. 输出（知识卡片 + Mock Feishu 表）
5. 记忆（User Memory 更新）

## 测试步骤

### 1. 事件采集（Chrome 插件 v0.2.10）
- 打开小红书笔记详情页 → 浏览（note_view）→ 点收藏（note_collect）
- Console 验证：`[ReCollect][collect] clicked` + `emit note_collect {note_id}`
- popup「导出事件」→ `recollect_events_*.jsonl`

### 2. 事件路由（event_router）
- `note_view` → event_ingest → RawNote
- `note_collect` → pending_store

### 3. pending 解析（content_resolver）
- pending task 匹配 note_view 内容 → RawNote（resolved）
- 未匹配 → 保持 pending

### 4. Pipeline 处理
- P2 筛选（LLM: keep/review/drop）
- P3 总结（LLM: category/tags/tldr）
- P4 写入（write_records）
- Mock Feishu（mock_feishu_bitable.jsonl）
- P6 索引（Chroma）

### 5. 用户记忆（Memory Builder）
- 读取 summary + audit + events
- 生成 topics（interest_score）+ preferences
- 输出 `[Memory] updated user profile`

## 测试结果

### 成功数量
- note_collect 事件: **4/4 进入 pending** ✅
- pending 解析: **4/4 resolved** ✅
- note_view → RawNote: **4/4** ✅
- P2 筛选: **2 keep / 1 review / 1 drop**（真实 LLM）✅
- P3 总结: **4 条** ✅
- Mock Feishu 表: **1 行** ✅
- User Memory: **3 个主题 + 内容偏好** ✅

### 失败数量
- **0**（全链路无失败）

### 失败原因
- 无

### 关键验证输出

```
[1/3] 路由事件 ← data\events
  note_view 新增: 4 | note_collect 新增 pending: 4
[2/3] 解析 pending task
  [resolver] note_collect 6a6d5ba1 -> resolved raw_note_id 6a6d5ba1 (title=zyy 签售态度)
  [resolver] note_collect 6a76a50f -> resolved raw_note_id 6a76a50f (title=原来《梦幻西游》...)
  [resolver] note_collect 6a6e1afd -> resolved raw_note_id 6a6e1afd (title=聪明人不要随便进大厂)
  [resolver] note_collect 6954c9ad -> resolved raw_note_id 6954c9ad (title=台湾 梅山乡地道家乡早餐)
  resolved: 4 | 仍 pending: 0
[Memory] updated user profile (4 notes, 3 topics)
```

### user_memory.json 样例（部分）

```json
{
  "topics": [
    {"name": "生活方式", "interest_score": 1.0, "note_count": 2},
    {"name": "职场发展", "interest_score": 0.61, "note_count": 1},
    {"name": "技能学习", "interest_score": 0.34, "note_count": 1}
  ],
  "preferences": {"content_type": ["图文"]},
  "updated_at": "2026-08-08T17:35:01",
  "stats": {"notes_processed": 4, "collect_count": 4, "view_count": 4}
}
```

## 结论

- ✅ **MVP 闭环成立**: 收藏 → 知识卡片 → 用户记忆
- ✅ 连续处理多条收藏事件无阻塞
- ✅ 零失败、零数据污染（v0.2.8 修复后无 /board 误采）
- ⏳ 待后续: 真实飞书接入 / 记忆的推荐使用 / 兴趣趋势（跨运行聚合）

---
*记录于 MVP E2E 验证（2026-08-08）*
