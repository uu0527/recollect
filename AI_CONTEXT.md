# ReCollect AI Context

更新时间： 2026-08-06 (Phase 3 完成 - 真实 LLM 接入 + Eval 对比评估)

# 1. 项目定位

项目名称： ReCollect（拾遗）

一句话： 收藏激活助手。

目标： 将用户沉睡收藏自动转化为：
- 结构化知识
- 可检索记忆
- 可复用内容资产

---

# 2. 当前目标

V1 Demo： 截止： 2026-08-15

必须完成：
[x] PRD冻结
[x] 数据采集 P1  (Mock 10 条：2 广告 / 3 灰区 / 5 干货)
[x] AI筛选 P2    (真实 LLM + Mock 双模式，三态决策：keep/review/drop)
[x] AI归纳 P3    (真实 LLM + Mock 双模式，分类+TLDR+要点+可执行建议，严格 JSON)
[x] 飞书写入 P4  (Mock Bitable + FeishuBitable 真实 SDK 封装 + note_id 去重 + 回读校验 + 触发 P6 增量索引)
[x] 独立审计 P5  (GSB 三维：保真×0.4 + 覆盖×0.35 + 分类×0.25)
[x] Memory检索 P6 (ChromaDB + sentence-transformers 真实向量库，Mock 回退)
[x] Eval        (P2/P3/P6 评分脚本 + Gold 标注集 + 反例库 + Mock vs Real LLM 对比评估)

---

# 3. 技术原则

必须遵守：
1. 模块解耦
2. 阶段之间使用JSON/JSONL通信
3. 每个阶段可以单独运行
4. 支持task_id
5. 失败可以重跑
6. 优先简单可靠

---

# 4. 当前架构

输入： 收藏内容
↓
P1 Collect
↓
P2 Screen (LLM 三态筛选)
↓
P3 Summary (LLM 归纳)
↓
P5 Audit (独立 LLM 审计)
↓
P4 Write (飞书 Bitable)
↓
P6 Memory (向量检索问答)

## 4.1 LLM Provider 层（Phase 3 新增）

```
pipeline/_llm/
├── base.py             # LLMClient 抽象接口 (complete / json_complete)
├── mock.py             # MockLLMClient (schema scaffold 模拟真实行为)
├── openai_provider.py  # OpenAICompatibleClient (openai/kimi/deepseek/qwen 共用)
├── factory.py          # get_provider(stage, force_new) 工厂
└── prompts.py          # 版本化 prompt 管理 (get_prompt / list_versions)
```

- `MODEL_CONFIG` 按阶段配置 provider（p2/p3/p5/p6 可分别指定不同 provider）
- 支持：`mock / openai / kimi / deepseek / qwen`
- api_key 缺失自动回退 mock（不阻断 pipeline）
- P5 使用 `force_new=True` 确保与 P3 实例隔离

---

# 5. 当前代码状态

## 已完成

### Phase 1-2（Mock MVP）
- [x] 完整目录结构：pipeline/p1~p6 + data/01_raw~06_memory + memory/eval + frontend + scripts
- [x] 数据契约 schemas.py：RawNote / ScreenedNote / SummarizedNote / WriteRecord / AuditResult / RAGResult
- [x] 全局配置 config.py：路径生成器 + P2_THRESHOLDS + FEISHU + RAG + STAGE_ORDER
- [x] P1~P6 Mock 全链路 + run.py 统一 Harness + demo_runner 兜底

### Phase 3（真实能力接入）
- [x] **pipeline/_llm/ 统一 LLM 接口层**：LLMClient 抽象 + Mock + OpenAI 兼容（4 家共用）+ 工厂 + prompt 版本化
- [x] **P2/P3/P5 接入真实 LLM**：双模式（provider 切换），失败自动回退 mock，后处理归一化（_normalize_p2/p3/p5）
- [x] **P4 飞书接入**：FeishuBitable 封装 lark-oapi（指数退避重试），配置缺失/失败回退 mock
- [x] **P6 真实向量库**：ChromaDB + sentence-transformers（bge-small-zh-v1.5），失败回退 mock
- [x] **Qwen 真实 LLM 联通**：.env 配置 QWEN_API_KEY，p2/p3/p5 全用 qwen 跑通
- [x] **P2 prompt v2**：明确三态判据 + 3-shot examples，修复 Qwen 全 review 问题（0 错误）
- [x] **Mock vs Real 对比评估**：scripts/eval_compare.py + eval_report_v2.md

### 关键文件
- `pipeline/_llm/*` — LLM 接口层（base/mock/openai_provider/factory/prompts）
- `scripts/eval_compare.py` — Mock vs Real 对比评估脚本
- `memory/eval/scoring.py` — P2/P3/P6 评分（含 BASE_DIR 修复）
- `memory/eval/eval_report_v2.md` — 对比评估报告
- `memory/eval/compare_mock_vs_qwen_eval_v2.json` — v2 评估数据

## 开发中
无

## 下一任务
V1 demo 收尾 + 真实链路增强：
1. P5 换独立 provider（deepseek/kimi），实现审计与生成模型隔离（P3/P5 当前同为 qwen，自评偏高）
2. P5 prompt v2：提高审计严格度，解决区分度不足（当前审计分集中在 0.95-1.0）
3. P6 扩充评估：语料扩到 100+ 条 + 20-30 个 gold query
4. P6 回答接入真实 LLM（当前 mock 模板生成）
5. P1 浏览器插件 MV3（真实采集通道）
6. P4 接真实飞书（需要 FEISHU_APP_ID / SECRET / BITABLE_TOKEN）
7. Eval：扩充 Gold 到 100~150 条真实标注
8. 记录一周北极星指标（digest 打开率 / 归纳回访率 / 检索真实使用次数 / 落灰救回率）

---

# 6. 当前已知问题

- P3/P5 同为 qwen：审计存在自我确认偏差风险，P5 审计分偏高（0.986 vs Mock 0.8）
- P6 P@k=0.2：小数据集（8 条语料）正常现象，top1 全命中 gold，扩数据后自然改善
- P5 审计区分度不足：4 条审计 3 条满分，需要 prompt 调优
- .env 中 DEEPSEEK_API_KEY 为占位符"你的key"，需真实 key 才能用 deepseek
- data/ 目录为运行时产物，gitignore 部分文件

---

# 7. 决策记录

## 2026-08-05
决定：
采用：
Trae负责主开发
WorkBuddy负责review
ChatGPT负责：
- 任务拆解
- 架构判断
- 验收

## 2026-08-05 (Phase 1)
新增决定：
1. 阶段调度顺序固定写入 config.STAGE_ORDER = ["p1","p2","p3","p5","p4","p6"]（P5 先于 P4，审计通过才写入）
2. 各模块统一入口为 `run(task_id, **kwargs)`，P6 额外提供 `build_index` / `query` 原子接口
3. 阶段间 100% 通过 JSON/JSONL 文件通信，无内存态传递（符合技术原则第2条）
4. 默认使用 mock adapter（FEISHU.use_mock = True），不接真实 API 也可跑通全链路

## 2026-08-05 (Phase 2)
新增决定：
5. **P6 索引前置写入 P4**：P4 每次写成功即调用 P6.build_index(incremental=True)，而不是在 P6 首次查询时全量重建（解决「记忆系统如何应对持续增长」面试点）
6. **P5 先于 P4 执行**：写入前必须过审计（仅 only_audited=True 且 audit_score >= 0.6 的 summary 才允许写）；默认 audit_ratio=0.5 demo 抽样，生产可调 1.0
7. **Mock 体系三要素统一**：Embedding(MD5 归一化) / VectorStore(JSON+余弦) / LLM(启发式+模板)，API 与真实方案 1:1，Phase 3 接入真实服务时**零改调用方**
8. **RAG 回答强约束**：RAGResult 必须带 retrieved_note_ids；P6.query 不允许多轮（V1 OUT），避免范围蔓延
9. **反例库统一进 Eval**：P2/P3/P6 所有错误案例统一走 `memory/eval/error_cases_{task_id}.jsonl`，迭代同一套机制
10. **兜底脚本策略**：run.py(CLI click) + scripts/demo_runner.py(直接 import) 双通道，防止环境里 Python alias 异常导致 demo 跑不起来

## 2026-08-06 (Phase 3)
新增决定：
11. **LLM Provider 抽象**：`pipeline/_llm/base.py` 定义 LLMClient 接口；json_complete 的降级策略**不写死在 base**，由各 provider 自行实现
12. **MockLLMClient 模拟真实行为**：通过 `_scaffold_from_schema()` 生成 schema 合规假数据，而非包装旧启发式逻辑
13. **Factory 接口规范**：`get_provider(stage, force_new=False)` 显式类型注解，P5 强制 `force_new=True` 实例隔离
14. **OpenAICompatibleClient 保留 provider_name**：单类覆盖 openai/kimi/deepseek/qwen，仅 base_url 不同，用于日志/eval 追踪
15. **Prompt 版本化**：`prompts.py` 用 `_REGISTRY` + `_LATEST` 指针管理多版本，改 prompt 必须新增版本不允许原地改
16. **LLM 输出后处理归一化**：`_normalize_p2/p3/p5()` 映射非法值到合法范围（而非严格 schema 校验，避免 LLM 输出失败），pass `schema=None` 跳过严格校验
17. **P2 prompt v2**：明确 keep/review/drop 判据 + 判定顺序 + 3-shot examples；修复 Qwen 全 review（7 错 → 0 错）
18. **评估对比框架**：scripts/eval_compare.py 用不同 task_id（{prefix}_mock / {prefix}_real）分别跑 Mock 与 Real，避免 env 覆盖污染

---

# 8. 禁止事项

禁止：
- 用户登录
- 多用户系统
- SaaS后台
- 多平台同步
- 复杂UI
- 超范围功能

如果发现需求： 先提出。 不要自行开发。

---

# 9. Agent规则

## Trae
角色： Lead Engineer
负责： 代码实现
提交后更新：
- 完成内容
- 修改文件
- 当前风险

## WorkBuddy
角色： Reviewer
负责：
- Bug发现
- 架构检查
- 测试建议
不要大规模重构。

## ChatGPT
角色： Project Manager
负责：
- 优先级
- 任务拆解
- 验收标准
