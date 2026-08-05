# ReCollect AI Context

更新时间： 2026-08-05 (Phase 2 Done - 主链路 Mock 跑通)

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
[x] AI筛选 P2    (启发式 Mock LLM，三态决策：keep/review/drop)
[x] AI归纳 P3    (Mock：分类+TLDR+要点+可执行建议，严格 JSON)
[x] 飞书写入 P4  (Mock Bitable + note_id 去重 + 回读校验 + 触发 P6 增量索引)
[x] 独立审计 P5  (GSB 三维：保真×0.4 + 覆盖×0.35 + 分类×0.25)
[x] Memory检索 P6 (Mock embedding 384 维 + Mock 向量库 + 强制返回 retrieved_note_ids)
[x] Eval        (P2/P3/P6 评分脚本 + Gold 标注集 + 反例库 + memory/eval/scoring.py)

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
P2 Screen
↓
P3 Summary
↓
P5 Audit
↓
P4 Write
↓
P6 Memory

---

# 5. 当前代码状态

## 已完成
- [x] Phase 1 项目骨架初始化（已合并进 Phase 2 状态描述）
- [x] 完整目录结构：pipeline/p1~p6 + data/01_raw~06_memory + memory/eval + frontend + scripts
- [x] Python 环境声明：requirements.txt + pyproject.toml（可选依赖 llm/rag/eval/feishu/all）
- [x] 数据契约 schemas.py：RawNote / ScreenedNote / SummarizedNote / WriteRecord / AuditResult / RAGResult + 4 个 JSONL/JSON IO 函数
- [x] 全局配置 config.py：路径生成器(path_raw…path_rag_result) + P2_THRESHOLDS + FEISHU(use_mock=True) + RAG + STAGE_ORDER = [p1,p2,p3,p5,p4,p6]
- [x] P1 采集 Mock：内置 10 条 Demo 收藏（2 广告 / 3 灰区 / 5 干货），支持 input_urls / input_file 手动导入双路径
- [x] P2 筛选 Mock：关键词启发式 + 三态阈值路由（ad_drop 0.85 / review_low 0.3 / value_keep_min 3），输出 decision/ad_confidence/value_score/reason/content_type
- [x] P3 归纳 Mock：L1_L2_RULES 正则分类 + TAG_RULES 标签 + 编号点抽取 + TLDR 模板 + actionable 模板，严格 JSON 数组
- [x] P5 审计 Mock：与 P3 完全隔离，audit_ratio=0.5 固定 seed 抽检，三维加权 audit_score = 0.4×fidelity + 0.35×coverage + 0.25×category
- [x] P4 写入 Mock：MockBitable 本地 JSONL + note_id 去重 + 字段 mapping + 写后回读校验 + 写成功触发 P6.build_index(incremental=True)（索引前置）
- [x] P6 RAG Mock：MockEmbedding(MD5 归一化 384 维) + MockVectorStore(余弦 top-k) + 模板化回答；RAGResult 强制附 retrieved_note_ids + retrieved_chunks；默认 3 个 Demo 问题
- [x] run.py 统一 Harness：click CLI（--task_id --stage all/p1..p6 --dry_run --skip_multimodal --model_override --query），参数透传
- [x] scripts/demo_runner.py：不依赖 click 的 E2E Demo Runner（Python alias 故障时兜底）
- [x] memory/eval/scoring.py：P2 广告召回率 / P3 审计分 + 通过线 / P6 Precision@k Recall@k RelevantRate，+ Gold 10 条标注集 + 反例库
- [x] README.md 完整重写：定位 + 目录结构 + 阶段契约表 + 关键设计点 + 快速开始（安装/全链路/单阶段/Eval）+ 核心文件链接表 + 技术原则 + 禁止 + Phase 3 路线

## 开发中
无

## 下一任务
Phase 3（真实链路接入）：
1. P2/P3/P5 接入真实 LLM API（openai/kimi/deepseek），保留 Mock provider
2. P1 接入浏览器插件 MV3 + 手动导入链接
3. P4 接入真实飞书多维表格 + digest 文档
4. P6 升级为 sentence-transformers + chromadb（接口不变）
5. Eval：扩充 Gold 到 100~150 条真实标注；P6 20-30 个真实查询；反例库持续累积
6. 记录一周北极星指标（digest 打开率 / 归纳回访率 / 检索真实使用次数 / 落灰救回率）

---

# 6. 当前已知问题

- 当前 Windows 系统 `python` alias 指向 Microsoft Store 占位符，需 `py -3` 或真实解释器路径；故新增 scripts/demo_runner.py 作为不依赖 click 的兜底脚本。代码级导入路径与包结构已静态验证。

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
