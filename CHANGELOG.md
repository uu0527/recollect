# ReCollect Changelog

## 2026-08-06 (Phase 3 - 真实能力接入 + Eval 对比评估)

完成：
- **LLM Provider 抽象层** `pipeline/_llm/`（base/mock/openai_provider/factory/prompts）
  - LLMClient 接口（complete / json_complete），降级策略不写死 base
  - MockLLMClient 通过 schema scaffold 模拟真实行为
  - OpenAICompatibleClient 单类覆盖 openai/kimi/deepseek/qwen
  - Prompt 版本化管理（_REGISTRY + _LATEST 指针）
- **P2/P3/P5 接入真实 LLM**：双模式 provider 切换 + LLM 失败回退 mock + 后处理归一化
- **P4 飞书接入**：FeishuBitable 封装 lark-oapi（指数退避重试）
- **P6 真实向量库**：ChromaDB + sentence-transformers（bge-small-zh-v1.5）
- **Qwen 真实 LLM 联通**：demo02 全链路端到端跑通
- **P2 prompt v2**：明确三态判据 + 3-shot examples，修复全 review 问题
- **Mock vs Real 对比评估**：scripts/eval_compare.py + eval_report_v2.md

Git 提交（8 个）：
- `11da5e2` add qwen llm provider support
- `5ce4a4a` Phase 3: LLM Provider Layer + Real LLM + Feishu + Chroma
- `905d05c` fix: p6 chroma query, p5 heuristic fallback, config syntax, qwen warning
- `1220287` fix: add post-processing normalization for P2/P3/P5 + qwen config
- `a702be9` add: Mock vs Real LLM comparison eval script + eval results
- `39fb3c7` fix: scoring.py BASE_DIR path bug (parents[1] -> parents[2])
- `856e4c1` feat: P2 prompt v2 with explicit three-way criteria + few-shot examples
- `a102a94` docs: eval report v2 - Mock vs Qwen comparison results

关键指标（10 条 gold 标注集）：
- P2：Qwen v2 三态决策 0 错误（v1 曾 7 错）
- P3：Qwen 分类准确率 1.0（Mock 0.513）
- P5：Qwen 审计分 0.986（偏高，待模型隔离）
- P6：R@k=100%，top1 全命中 gold（P@k=0.2 小数据集正常）

当前状态：Phase 3 完成 ✅ — 真实 LLM 链路 + 对比评估就绪

下一步：
1. P5 换独立 provider（审计与生成模型隔离）
2. P6 扩充语料 + gold query（100+ 条 / 20-30 query）
3. P1 浏览器插件 MV3
4. P4 接真实飞书

---

## 2026-08-05 (Phase 1 - 项目骨架初始化)

完成：
- 完整目录结构落地
  - pipeline/: p1_collect / p2_screen / p3_summary / p4_write / p5_audit / p6_memory
  - data/: 01_raw / 02_screened / 03_summary / 04_write / 05_audit / 06_memory (+ chroma_index)
  - memory/eval 评估目录
  - frontend/ scripts/ 预留
- Python 环境声明：requirements.txt + pyproject.toml (可选依赖分组: llm/rag/eval/feishu/all)
- 数据契约 schemas.py：6 个 dataclass + JSONL/JSON 通用 IO（load_jsonl / dump_jsonl / dump_json / load_json）
  - RawNote(P1) / ScreenedNote(P2) / SummarizedNote(P3) / WriteRecord(P4) / AuditResult(P5) / RAGResult(P6)
- 全局配置 config.py：
  - 阶段路径生成函数 (path_raw / path_screened / …)，全部按 task_id 前缀，幂等
  - P2 阈值、FEISHU 默认 mock、RAG top_k
  - STAGE_ORDER = ["p1", "p2", "p3", "p5", "p4", "p6"]（P5 审计先于 P4 写入）
- P1~P6 模块接口定义：每个 pipeline 子包的 `__init__.py` 中声明 `run(task_id, **kwargs)` 签名 + docstring
  - P6 额外提供 build_index / query 两个原子接口
  - 所有接口 raise NotImplementedError，Phase 2 填充
- run.py 统一 Harness CLI 入口（基于 click）
  - 参数：--task_id (required) / --stage (all|p1|p2|p3|p5|p4|p6) / --dry_run / --skip_multimodal / --model_override / --query
  - --dry_run 可打印执行顺序，验证入口可用

修改文件：
- 新增: requirements.txt, pyproject.toml, schemas.py, config.py, run.py
- 新增: pipeline/p{1..6}_*/__init__.py （共 6 个包）
- 更新: AI_CONTEXT.md (#5 #6 #7 更新 Phase 1 状态)

当前状态：Phase 1 完成 ✅ — 骨架就绪，待 Phase 2 实现业务逻辑

验收：
- [x] run.py CLI 参数解析框架就绪（--dry_run 仅打印计划，不调用业务）
- [x] 所有模块有统一 run 接口签名
- [x] Schema / Config / StageOrder / 数据目录 全部定义完毕

下一步：
Trae（Phase 2）：
1. P1 mock 数据生成器（10 条 demo 收藏）
2. P2 mock LLM 筛选（三态决策 + 阈值路由）
3. P3 mock 归纳（生成严格 JSON）
4. P5 mock 审计（GSB 三维打分）
5. P4 mock 飞书写入（去重 + 写入记录）
6. P6 mock embedding + 检索问答
7. 端到端 demo：`python run.py --task_id demo01 --stage all` 跑通并生成所有阶段文件

验收标准：
- 一次运行生成 01_raw~06_memory 全部阶段产物
- 每个阶段 JSONL/JSON 可用 schemas.py 对应 dataclass 反序列化无报错
