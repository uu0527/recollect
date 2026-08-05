# ReCollect（拾遗）—— 收藏夹智能整理助手

> 收藏激活助手：不做「稍后读」，做「收藏激活」—— 把落灰的小红书收藏自动整理成可检索、可使用的个人知识库。
> V1 Demo 交付截止：2026-08-15

---

## 1. 项目定位

把用户沉睡收藏内容（小红书为主）自动跑完整条 AI pipeline：

```
收藏链接/P1采集  →  P2 AI筛选  →  P3 AI归纳  →  P5 独立审计  →  P4 飞书写入
                                                          ↘
                                                            P6 记忆层（向量检索问答）
```

**卖点：**
- 三态筛选（keep / review / drop），不漏杀好内容也不放广告
- **独立审计**（P5 用独立模型 vs P3 生成模型隔离），降低幻觉污染知识库
- 写入飞书时同步建 embedding 索引 → P6 随时提问，回答强制附来源 `retrieved_note_ids`
- 全链路幂等：所有产物带 `task_id` 前缀，失败/重跑直接覆盖，无重复记录

---

## 2. 目录结构

```
recollect/
├── PRD.md                          # 产品需求（已冻结）
├── AI_CONTEXT.md                   # 三方共享记忆（Trae / WorkBuddy / ChatGPT）
├── CHANGELOG.md                    # 开发日志
├── README.md                       # 本文件
├── requirements.txt                # Python 依赖
├── pyproject.toml                  # 包定义 + 可选依赖分组 (llm/rag/eval/feishu/all)
├── run.py                          # ⭐ 统一 Harness CLI 入口
│
├── schemas.py                      # 6 个核心数据 Schema + JSONL/JSON 通用 IO
├── config.py                       # 路径生成器 / 阈值 / 飞书 / RAG / STAGE_ORDER
│
├── pipeline/
│   ├── p1_collect/__init__.py      # P1 采集（Mock Demo 数据 10 条）
│   ├── p2_screen/__init__.py       # P2 广告识别 + 三态决策（阈值路由）
│   ├── p3_summary/__init__.py      # P3 结构化归纳（严格 JSON）
│   ├── p5_audit/__init__.py        # P5 独立审计（GSB 三维打分，固定 seed 抽检）
│   ├── p4_write/__init__.py        # P4 飞书写入（mock adapter + note_id 去重 + 回读校验）
│   └── p6_memory/__init__.py       # P6 RAG（mock embedding + mock 向量库 + 强制附来源）
│
├── data/                           # 全部阶段产物（task_id 前缀）
│   ├── 01_raw/{task_id}_notes.jsonl
│   ├── 02_screened/{task_id}_screened.jsonl
│   ├── 03_summary/{task_id}_summary.json
│   ├── 04_write/{task_id}_write_records.jsonl   +   mock_feishu_bitable.jsonl
│   ├── 05_audit/{task_id}_audit.jsonl
│   └── 06_memory/{task_id}_rag_q1.json …  +  chroma_index/{task_id}/store.json
│
├── memory/eval/
│   └── scoring.py                  # P2/P3/P6 评测脚本 + Gold 标注集 + 反例库
│
├── scripts/
│   └── demo_runner.py              # 不依赖 click 的端到端 Demo Runner（兜底脚本）
│
├── frontend/                       # 占位（V1 OUT：复杂 UI 不做）
└── scripts/                        # 工具脚本
```

---

## 3. 架构说明（V1）

### 3.1 阶段契约（阶段间 100% JSON/JSONL 文件通信）

| 阶段 | 输入文件 | 输出文件 | 输出 Schema |
|---|---|---|---|
| **P1** 采集 | URL 列表 / 手动链接 | `01_raw/{task_id}_notes.jsonl` | `RawNote`(note_id, url, title, content, images, metadata) |
| **P2** 筛选 | P1 JSONL | `02_screened/{task_id}_screened.jsonl` | `ScreenedNote`(decision: keep/review/drop, ad_confidence, is_ad, content_type, value_score, reason) |
| **P3** 归纳 | P1 + P2 JSONL | `03_summary/{task_id}_summary.json` (数组) | `SummarizedNote`(title, category_l1/l2, tags, tldr, key_points, actionable, content_type) |
| **P5** 审计 | P1 + P3 | `05_audit/{task_id}_audit.jsonl` | `AuditResult`(audit_score, fidelity/coverage/category, comments) |
| **P4** 写入 | P3 + P5 | `04_write/{task_id}_write_records.jsonl` + `mock_feishu_bitable.jsonl` | `WriteRecord`(write_success, dedup_hit, error_msg) |
| **P6** 检索 | P3 summary → embedding 索引 | `06_memory/{task_id}_rag_qN.json` | `RAGResult`(query, **retrieved_note_ids**, answer, confidence, retrieved_chunks) |

执行顺序由 `config.STAGE_ORDER = ["p1","p2","p3","p5","p4","p6"]` 固定（P5 先于 P4，审计通过才入库）。

### 3.2 关键设计点

- **三态决策（P2）**：ad_confidence ≥0.85 → `drop`；ad_confidence <0.3 且 value_score ≥3 → `keep`；其余 → `review`。review 进飞书「待确认」视图 = 标注数据源。
- **独立审计（P5）**：三维加权 `audit_score = 0.4×保真 + 0.35×覆盖 + 0.25×分类`，与 P3 归纳逻辑完全隔离，避免自我确认。
- **写入三保险（P4）**：① note_id 去重 ② 写后回读校验 ③ 写成功即触发 P6 增量建索引（随写随建，而非全量重建）。
- **记忆层（P6）**：chunk = `tldr + tags + key_points + actionable`，查询时强制返回 `retrieved_note_ids` 可追溯，不做多轮对话（V1 OUT）。

---

## 4. 快速开始

### 4.1 安装依赖

当前所有模块都是 **Mock 实现**，不接真实 LLM / 飞书 / Chroma / SentenceTransformer，安装最小依赖即可跑全链路：

```bash
cd recollect
pip install click pyyaml tqdm pandas jsonschema requests beautifulsoup4
# 或 完整依赖（真实接入 LLM/RAG 时）：
# pip install -r requirements.txt
```

### 4.2 一键全链路 Demo

```bash
# 方式一：通过 CLI Harness（推荐）
python run.py --task_id demo01 --stage all

# 方式二：通过兜底脚本（不依赖 click）
python scripts/demo_runner.py demo01
```

完成后查看 `data/` 目录下所有阶段产物。

### 4.3 单阶段重跑（断点续跑/调试）

```bash
# 只重跑筛选
python run.py --task_id demo01 --stage p2

# 只重跑审计
python run.py --task_id demo01 --stage p5

# 只跑 P6 RAG（使用默认 3 个内置问题）
python run.py --task_id demo01 --stage p6

# P6 直接问一个问题（CLI 单问模式）
python run.py --task_id demo01 --stage p6 --query "健身新手怎么安排饮食？"

# 先 Dry Run 看看会执行什么
python run.py --task_id demo01 --dry_run
```

支持的 CLI 参数：

```
--task_id        str    必选，任务 ID（幂等前缀）
--stage          str    all | p1 | p2 | p3 | p5 | p4 | p6   (默认 all)
--dry_run        flag   只打印阶段顺序，不实际执行
--skip_multimodal flag  P3 跳过图片/视频理解（当前已是纯文本，占位兼容）
--model_override str    p3=xxx 模型覆盖（Phase 3 真实接入时生效）
--query          str    P6 CLI 单问
```

### 4.4 跑评测（Eval）

```bash
python memory/eval/scoring.py demo01
```

输出 3 份报告到 `memory/eval/`：
- `report_demo01.json`：P2 广告识别 + P3 审计分 + P6 检索指标的汇总
- `error_cases_demo01.jsonl`：反例库（预测错误的 P2 note）
- `gold_dataset_demo01.json`：Gold 标注集（P2 10 条 + P6 3 query）

当前 Mock 版本指标参考值（10 条 Demo）：
- P2 广告召回率 ≈ 100%（2 条广告全 drop），误杀率 ≈ 0%，review 率 ≈ 30%
- P3 平均审计分 ≥ 0.70
- P6 平均相关率 ≥ 60%（3 个内置问题）

---

## 5. 核心文件一览（代码入口）

| 文件 | 作用 |
|---|---|
| [run.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/run.py) | 统一 Harness CLI：click 参数解析 + 阶段调度 |
| [schemas.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/schemas.py) | RawNote / ScreenedNote / SummarizedNote / WriteRecord / AuditResult / RAGResult + load_jsonl/dump_jsonl… |
| [config.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/config.py) | `path_raw()`… 路径生成器、P2_THRESHOLDS、FEISHU(use_mock=True)、STAGE_ORDER |
| [pipeline/p1_collect/\_\_init\_\_.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/pipeline/p1_collect/__init__.py) | 内置 10 条 Demo 收藏（2 广告 / 3 灰区 / 5 干货），生成 RawNote |
| [pipeline/p2_screen/\_\_init\_\_.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/pipeline/p2_screen/__init__.py) | 启发式模拟 LLM：关键词命中 + 阈值路由 → keep/review/drop |
| [pipeline/p3_summary/\_\_init\_\_.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/pipeline/p3_summary/__init__.py) | 严格 JSON：L1/L2 分类 + 标签 + TLDR + 编号要点 + 可执行建议 |
| [pipeline/p5_audit/\_\_init\_\_.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/pipeline/p5_audit/__init__.py) | GSB 三维打分 + 固定 seed audit_ratio=0.5 抽检 |
| [pipeline/p4_write/\_\_init\_\_.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/pipeline/p4_write/__init__.py) | MockBitable：去重 + 字段 mapping + 回读校验 + 同步触发 P6 增量索引 |
| [pipeline/p6_memory/\_\_init\_\_.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/pipeline/p6_memory/__init__.py) | Mock 向量库（MD5 归一化 embedding + 余弦 top-k），回答必附 retrieved_note_ids |
| [memory/eval/scoring.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/memory/eval/scoring.py) | P2 广告召回率 / P3 审计分 / P6 Precision@k Recall@k；+ Gold 集 + 反例库 |

---

## 6. 技术原则（强制遵守）

1. **模块解耦**：阶段间不做内存态传递，一律通过 `data/{stage}/{task_id}_*` 文件契约。
2. **JSON/JSONL** 通信，Schema 集中在 [schemas.py](file:///d:/Users/aimee.yu/Documents/trae_projects/knowledge/recollect/schemas.py)。
3. **每个阶段单独可跑**：`--stage p2` 直接跑，不依赖前面阶段必须在同一进程。
4. **支持 task_id**：所有输出文件名带前缀，不同任务互不干扰。
5. **失败可重跑**：同 task_id 重跑 = 覆盖写（幂等）；P4 的 note_id 去重保证写入不重复。
6. **优先简单可靠**：Mock 可跑通 → 再接真实 LLM / 飞书 / 向量库；不引入 Airflow / Temporal 等重型框架。

---

## 7. 禁止开发（V1 OUT）

- ❌ 用户登录 / 多用户系统 / SaaS 后台
- ❌ 复杂 UI（飞书 + memory/eval 评分输出足矣）
- ❌ 多平台同步（小红书以外为 V2+）
- ❌ 多轮对话 / 追问澄清（P6 只做检索问答 PoC）
- ❌ 全自动定时同步（V1 手动触发）
- ❌ 视频人声 ASR（视频抽帧即可，音频不做）

超范围需求 → 先提，不要自行开发。

---

## 8. 下一步（Phase 3）

1. P2/P3/P5 接入真实 LLM API（openai / kimi / deepseek），Mock 模式保留 `provider="mock"`
2. P1 接入浏览器插件 MV3 + 手动链接导入合规兜底通道
3. P4 接入真实飞书多维表格 + digest 文档
4. P6 升级为真实 sentence-transformers + chromadb（Mock 接口不变，替换 `_mock_embed` 和 `MockVectorStore` 即可）
5. P6 反例库扩充到 20-30 个真实问题
6. 运行日志记录「北极星指标」：digest 打开率 / 归纳回访率 / 检索真实使用次数 / 落灰救回率
