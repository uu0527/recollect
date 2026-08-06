# ReCollect — 项目交接文档（HANDOFF）

> 接手日期：2026-08-05
> 接手 Agent：WorkBuddy AI（Reviewer 角色）
> 上一阶段 Owner：Trae（Lead Engineer）
> 项目阶段：Phase 3 完成（真实 LLM 接入 + Eval 对比评估），V1 demo 收尾中

---

## 1. 一句话定位

ReCollect（拾遗）= **收藏激活助手**。  
把用户沉睡收藏自动跑完整 AI pipeline：采集 → 筛选 → 归纳 → **独立审计** → 飞书写入 → 检索问答。  
核心差异：① 三态筛选（keep / review / drop） ② 独立审计（隔离生成模型） ③ 强制附来源 `retrieved_note_ids`。

完整产品定位见 [`PRD.md`](./PRD.md)；阶段契约见 [`README.md`](./README.md) §3；API 状态见 [`AI_CONTEXT.md`](./AI_CONTEXT.md)。

---

## 2. 当前状态（Phase 3 完成）

✅ 主链路真实 LLM 跑通（Qwen），Mock 保留可切换；Mock vs Real 对比评估完成。

| 阶段 | 实现 | 文件 |
|---|---|---|
| P1 Collect | Mock 10 条 Demo + URL/文件双通道 | `pipeline/p1_collect/__init__.py` |
| P2 Screen | 真实 LLM + 启发式双模式，prompt v2（0 错误） | `pipeline/p2_screen/__init__.py` |
| P3 Summary | 真实 LLM 归纳（分类准确率 1.0） | `pipeline/p3_summary/__init__.py` |
| P5 Audit | 真实 LLM 审计 + 0.5 抽检（独立实例） | `pipeline/p5_audit/__init__.py` |
| P4 Write | Mock Bitable + FeishuBitable SDK 封装 + 去重 + 回读校验 | `pipeline/p4_write/__init__.py` |
| P6 Memory | ChromaDB + bge-small-zh 向量库，Mock 回退 | `pipeline/p6_memory/__init__.py` |
| LLM 层 | 统一接口 + 工厂 + prompt 版本化 | `pipeline/_llm/*` |
| Eval | P2/P3/P6 评分 + 对比评估脚本 + 报告 | `memory/eval/` + `scripts/eval_compare.py` |

### 2.1 一键跑通

```bash
cd recollect

# 全链路（默认 .env provider，当前 qwen）
python run.py --task_id demo01 --stage all

# Mock 模式强制走启发式
python run.py --task_id demo01 --stage p2 --model_override mock

# Mock vs Real 对比评估
python scripts/eval_compare.py --provider qwen --task_id eval

# 跑评测（单 task）
python memory/eval/scoring.py demo01
```

### 2.2 当前指标（Phase 3 实测，10 条 gold）

| 维度 | Mock | Qwen v2 |
|---|---|---|
| P2 决策错误 | 0 | **0** |
| P2 广告召回 | 100% | 100% |
| P3 分类准确 | 0.513 | **1.0** |
| P5 均审计分 | 0.800 | 0.986 |
| P6 召回率 | 100% | 100% |
| P6 精度@5 | 20% | 20% |

---

## 3. 关键设计决策（不可破坏）

> 完整决策记录见 [`AI_CONTEXT.md`](./AI_CONTEXT.md) §7

1. **执行顺序** `STAGE_ORDER = ["p1","p2","p3","p5","p4","p6"]` — P5 审计先于 P4 写入
2. **P6 索引前置** — P4 写成功即调 `P6.build_index(incremental=True)`，不查时全量重建
3. **P5 与 P3 完全隔离** — P5 只读 P1 raw + P3 summary，不复用 P3 启发式；Phase 3 用 `force_new=True` 实例隔离
4. **RAGResult 强约束** — `retrieved_note_ids` 必填，可追溯
5. **Mock/真实 1:1 接口** — provider 切换即可，调用方零改
6. **阶段间 100% JSON/JSONL** — 禁止内存态传递
7. **task_id 幂等** — 重跑 = 覆盖，P4 `note_id` 去重
8. **LLM 降级策略不进 base** — 各 provider 自行实现（用户 reviewer 意见）
9. **LLM 输出后处理归一化** — `_normalize_p2/p3/p5` 映射非法值，而非严格 schema 校验
10. **Prompt 版本化** — 改 prompt 必须新增版本，不允许原地改（保证 eval 可复现）

---

## 4. 已知问题（按优先级）

### P0 — 审计模型隔离
- P3/P5 同为 qwen，P5 自评偏高（0.986）— 应换独立 provider（deepseek/kimi）

### P0 — 文档一致性
- `PRD.md §2` 任务 checkbox 仍是 `[ ]`，实际已全部完成 — 需改为 `[x]`

### P1 — P5 区分度
- 审计分集中在 0.95-1.0，4 条审计 3 条满分 — prompt 调优提高严格度

### P1 — Eval 覆盖度
- Gold 集仅 10 条，统计意义弱 — 扩到 100~150 条
- P6 query 仅 3 个内置问题 — 扩到 20-30 个真实查询

### P1 — P4 真实飞书未接
- FeishuBitable SDK 已封装，但缺 FEISHU_APP_ID / SECRET / BITABLE_TOKEN

### P1 — P6 回答质量
- 回答仍用 mock 模板生成，未接真实 LLM

### P2 — P6 精度
- P@k=0.2（小数据集正常），扩语料后自然改善

### P2 — 浏览器插件
- P1 采集仍是 Mock，浏览器插件 MV3 未开发

---

## 5. 下一阶段（V1 demo 收尾）

> 完整路线见 [`AI_CONTEXT.md`](./AI_CONTEXT.md) §5

### P0（2026-08-15 前必做）

| 任务 | 说明 |
|---|---|
| P5 换独立 provider | deepseek / kimi，实现审计与生成模型隔离 |
| P5 prompt v2 | 提高审计严格度，解决区分度不足 |
| P1 浏览器插件 MV3 | 抓取小红书笔记 → 推本地 API |
| P4 真实飞书 | 多维表格 + digest 文档（需真实凭据） |
| Eval Gold 扩到 100~150 | 覆盖广告变体 / 灰区变体 |

### P1

| 任务 | 说明 |
|---|---|
| P6 扩充语料 + query | 100+ 条语料 / 20-30 真实 query |
| P6 回答接真实 LLM | 当前 mock 模板生成 |

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
