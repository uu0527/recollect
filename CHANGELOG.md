# ReCollect Changelog

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
