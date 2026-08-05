# ReCollect — 项目交接文档（HANDOFF）

> 接手日期：2026-08-05
> 接手 Agent：WorkBuddy AI（Reviewer 角色）
> 上一阶段 Owner：Trae（Lead Engineer）
> 项目阶段：Phase 2 Mock MVP 完成，Phase 3 真实接入待启动

---

## 1. 一句话定位

ReCollect（拾遗）= **收藏激活助手**。  
把用户沉睡收藏自动跑完整 AI pipeline：采集 → 筛选 → 归纳 → **独立审计** → 飞书写入 → 检索问答。  
核心差异：① 三态筛选（keep / review / drop） ② 独立审计（隔离生成模型） ③ 强制附来源 `retrieved_note_ids`。

完整产品定位见 [`PRD.md`](./PRD.md)；阶段契约见 [`README.md`](./README.md) §3；API 状态见 [`AI_CONTEXT.md`](./AI_CONTEXT.md)。

---

## 2. 当前状态（Phase 2 完成）

✅ 主链路 Mock 跑通，一键 demo 可生成全部阶段产物。

| 阶段 | 实现 | 文件 |
|---|---|---|
| P1 Collect | Mock 10 条 Demo + URL/文件双通道 | `pipeline/p1_collect/__init__.py` |
| P2 Screen | 关键词启发式 + 三态路由 | `pipeline/p2_screen/__init__.py` |
| P3 Summary | L1/L2 分类 + 严格 JSON | `pipeline/p3_summary/__init__.py` |
| P5 Audit | GSB 三维 + 0.5 抽检（独立） | `pipeline/p5_audit/__init__.py` |
| P4 Write | Mock Bitable + 去重 + 回读校验 + P6 索引前置 | `pipeline/p4_write/__init__.py` |
| P6 Memory | MD5 Embedding + JSON 向量库 + 强约束来源 | `pipeline/p6_memory/__init__.py` |
| Eval | P2/P3/P6 评分 + Gold 10 条 + 反例库 | `memory/eval/scoring.py` |

### 2.1 一键跑通

```bash
cd recollect

# 方式 A：CLI Harness（推荐）
python run.py --task_id demo01 --stage all

# 方式 B：兜底脚本（不依赖 click）
python scripts/demo_runner.py demo01

# 跑评测
python memory/eval/scoring.py demo01
```

产物落 `data/01_raw ~ 06_memory/` + `memory/eval/`。

### 2.2 期望指标（Mock 期基线）

- P2 广告召回率 ≈ 100%，误杀率 ≈ 0%，review 率 ≈ 30%
- P3 平均审计分 ≥ 0.70
- P6 平均相关率 ≥ 60%（3 个内置问题）

---

## 3. 关键设计决策（不可破坏）

> 完整决策记录见 [`AI_CONTEXT.md`](./AI_CONTEXT.md) §7

1. **执行顺序** `STAGE_ORDER = ["p1","p2","p3","p5","p4","p6"]` — P5 审计先于 P4 写入
2. **P6 索引前置** — P4 写成功即调 `P6.build_index(incremental=True)`，不查时全量重建
3. **P5 与 P3 完全隔离** — P5 只读 P1 raw + P3 summary，不复用 P3 启发式
4. **RAGResult 强约束** — `retrieved_note_ids` 必填，可追溯
5. **Mock/真实 1:1 接口** — Phase 3 接入真实服务时只换 provider，调用方零改
6. **阶段间 100% JSON/JSONL** — 禁止内存态传递
7. **task_id 幂等** — 重跑 = 覆盖，P4 `note_id` 去重

---

## 4. 已知问题（按优先级）

### P0 — 文档一致性
- `PRD.md §2` 任务 checkbox 仍是 `[ ]`，实际已全部完成 — 需改为 `[x]`

### P1 — 数据隔离
- `config.FEISHU.mock_output = data/04_write/mock_feishu_bitable.jsonl` 是 **全局文件**，多 task_id 写会混 — 建议改为 `data/04_write/{task_id}_mock_feishu_bitable.jsonl`

### P1 — Eval 覆盖度
- `memory/eval/scoring.py` 反例库仅覆盖 P2 决策错误，P3/P6 错误无机制记录
- Gold 集仅 10 条，统计意义弱

### P1 — P2 启发式盲区
- 软广 / 真人种草笔记（关键词命中数低）可能漏网
- 无 ML 模型，纯关键词

### P2 — P3 L2 推断
- `p3_summary._classify` 的 `l2_map` 关键词覆盖窄，"AI PM" / "数据" 等 L2 永远落"综合"

### P2 — P5 抽检
- `audit_ratio=0.5` + 固定 `seed=20260805` — 生产应改 1.0 或 per-task 切 seed

### P2 — P6 语义
- `_mock_embed` 基于 MD5 哈希，无真实语义 — 真实接入必须替换

---

## 5. 下一阶段（Phase 3 真实接入）

> 完整路线见 [`AI_CONTEXT.md`](./AI_CONTEXT.md) §5

### P0（2026-08-15 前必做）

| 任务 | 说明 |
|---|---|
| P2/P3/P5 接真实 LLM | openai / kimi / deepseek 三选一，保留 `provider="mock"` 切换 |
| P1 浏览器插件 MV3 | 抓取小红书笔记 → 推本地 API |
| P1 手动链接兜底 | URL/文件即可，已在 P1 mock 实现 |
| P4 真实飞书 | 多维表格 + digest 文档 |
| Eval Gold 扩到 100~150 | 覆盖广告变体 / 灰区变体 |

### P1

| 任务 | 说明 |
|---|---|
| P6 sentence-transformers + chromadb | 替换 `_mock_embed` / `MockVectorStore`，接口零改 |
| P6 反例库扩到 20~30 真实 query | 召回/相关率人工评估 |

### P2（V1 demo 后）

| 任务 | 说明 |
|---|---|
| 北极星指标埋点 | digest 打开率 / 归纳回访率 / 检索真实使用 / 落灰救回率 |
| P6 多轮对话 | ⚠️ PRD §7 标 OUT，慎做 |
| 真实 run 评测 | 100 条真实跑通 Eval，对照报告 |

---

## 6. 工程规范

### 6.1 阶段约定

- 每个阶段 `pipeline/pX_xxx/__init__.py` 暴露 `run(task_id, **kwargs)` 统一入口
- P6 额外暴露 `build_index` / `query` 原子接口
- 所有 IO 走 `data/{stage}/{task_id}_*` 文件契约
- Schema 集中 `schemas.py`，必须先于 IO 编写

### 6.2 提交规范（建议）

```
<type>(<scope>): <subject>

[body]

[footer]
```

- **type**: `feat` / `fix` / `docs` / `refactor` / `test` / `chore` / `perf`
- **scope**: `p1` / `p2` / `p3` / `p4` / `p5` / `p6` / `eval` / `harness` / `docs`
- **subject**: 50 字内，祈使句

### 6.3 验收清单

每次 PR 必跑：

```bash
python run.py --task_id demo01 --stage all
python memory/eval/scoring.py demo01
# 检查 data/ 6 个目录产物齐全
# 检查 EVAL_DIR/report_demo01.json 指标无回退
```

---

## 7. Agent 角色

| 角色 | Agent | 职责 |
|---|---|---|
| Lead Engineer | Trae | 代码实现，提交后更新 `AI_CONTEXT.md` §5 |
| Reviewer | WorkBuddy AI | Bug / 架构 / 测试，不重构 |
| Project Manager | ChatGPT | 优先级 / 任务拆解 / 验收 |

详见 [`AI_CONTEXT.md`](./AI_CONTEXT.md) §9。

---

## 8. 快速链接

| 文档 | 用途 |
|---|---|
| [`PRD.md`](./PRD.md) | 产品需求（已冻结 2026-08-05） |
| [`README.md`](./README.md) | 入口、阶段契约表、快速开始 |
| [`AI_CONTEXT.md`](./AI_CONTEXT.md) | 三方共享记忆 + 决策记录 |
| [`CHANGELOG.md`](./CHANGELOG.md) | 开发日志 |
| [`HANDOFF.md`](./HANDOFF.md) | 本文档 |
| `pyproject.toml` | 依赖分组（base / llm / rag / eval / feishu / all） |
| `requirements.txt` | 全量依赖声明（部分注释掉，按需启用） |

---

## 9. 联系 / 升级路径

- 任务分派：ChatGPT（PM）
- 代码冲突：WorkBuddy AI 裁定
- 范围争议：先看 PRD，超出 → 标 P0 暂停 + 提 PM

**接手第一步**：读 `AI_CONTEXT.md` §7 决策记录 + `README.md` §3 架构 → 跑一次 demo → 看 `memory/eval/report_demo01.json` 基线。
