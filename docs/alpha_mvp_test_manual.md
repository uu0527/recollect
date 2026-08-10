# ReCollect Alpha MVP Test Manual

> 版本：基于 commit `465c9f9`
> 用途：开发者 / PM / 测试人员验证 Alpha MVP 是否符合设计预期
> 说明：本文档基于当前代码实现，不包含未实现功能

---

## 1. MVP 核心链路说明

### 系统设计逻辑

```
User Query
    ↓
Chat UI (frontend)
    ↓ POST /api/chat
ChatRequest {query, session_id, context:{knowledge_id}?}
    ↓
AgentOrchestrator.handle()
    ├─ Context Resolver    （knowledge_id → Knowledge Asset，复用 StorageAdapter）
    ├─ Context Router      （判断是否注入 Knowledge Context）
    ├─ Retriever           （关键词检索 knowledge，top-5）
    ├─ Memory              （读取用户长期记忆 user_memory.json）
    ├─ Prompt Builder      （拼接 query + sources + context + memory）
    ├─ LLM                 （DeepSeek，失败降级 mock）
    ├─ Evaluator           （记录 eval/agent/agent_runs.jsonl）
    └─ Conversation Logger （记录 data/conversations/conversations.jsonl）
    ↓
Response {answer, sources, metadata{router, context_applied}}
```

### 各模块在 MVP 中的职责

| 模块 | 文件 | 职责 |
|---|---|---|
| Chat API | `backend/api/chat.py` | 接收 query/session_id/context，透传 orchestrator |
| AgentOrchestrator | `backend/agent/orchestrator.py` | 编排：Resolver → Router → Retriever → Memory → Prompt → LLM |
| Context Resolver | `orchestrator._resolve_context` | 按 knowledge_id 从 Supabase 取 Knowledge Asset |
| Context Router | `backend/agent/context_router/router.py` | 判断 query 与 context 相关性，决定是否注入 |
| Retriever | `backend/agent/retriever.py` | 关键词打分检索（title×3 / tldr×2 / tags×2）|
| Memory | `backend/agent/memory.py` | 读 user_memory.json（topics/preferences）|
| Prompt Builder | `backend/agent/prompt_builder.py` | 白名单注入 title/tldr/key_points≤3/tags |
| LLM | `pipeline/_llm/router.py` | DeepSeek（失败降级 mock 不阻断）|
| Evaluator | `backend/agent/evaluator.py` | agent_runs.jsonl（含 mode/context_applied）|
| Conversation Logger | `backend/agent/conversation_log.py` | conversations.jsonl（为未来分析预留）|

### 重点说明

**Context Router 为什么存在**
- 早期版本无条件注入（Full Injection），无关 query 也会把知识塞进 prompt，污染回答。
- Router 作为决策层，在注入前判断 query 与 Knowledge Asset 是否相关。

**Knowledge Context 如何决定是否注入**
- 输入：`query` + Knowledge Asset（title/tldr/key_points/tags）。
- 算法（V1）：Lexical + 意图词相似度。
  - 中文字符 2/3-gram + 英文词做 token 重叠打分。
  - 意图词增强：query 含"这个/总结/要点/细节"等知识相关意图词 → score=1.0。
- 决策：`score >= threshold(0.12)` → 注入；否则跳过（普通 Chat）。
- threshold 可配：环境变量 `CONTEXT_ROUTER_THRESHOLD`（默认 0.12）。

**Response 如何返回 sources**
- `sources`: retriever 命中的 knowledge 列表（note_id/title/url/category_l1/tldr）。
- `metadata.router`: `{should_inject, score, reason}` Router 决策明细。
- `metadata.context_applied`: 是否真正注入 Knowledge Context。
- 前端用 sources 渲染 source chips（最多 4 条，标题截断 18 字符）。

**Conversation Log 为什么记录**
- 为未来 Analysis Skill 提供真实对话数据（query/answer/router 决策/sources）。
- 本阶段只记录不分析。

---

## 2. 测试环境准备

### 前置条件

- Python 3.11+（项目使用 `.venv`）
- Node.js（仅前端语法检查用）
- Supabase 数据库（knowledge 表，含真实数据）
- LLM API Key（DeepSeek / Qwen 至少其一）

### 环境变量（`.env`）

| 变量 | 说明 |
|---|---|
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase 连接（knowledge 数据源）|
| `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` | LLM（or `QWEN_API_KEY`）|
| `RECOLLECT_P5_PROVIDER` | LLM provider 选择 |
| `CONTEXT_ROUTER_THRESHOLD` | （可选）Router 阈值，默认 0.12 |

### 后端启动

```bash
cd recollect
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

验证：`curl http://127.0.0.1:8000/health` → `{"status":"ok","service":"recollect-agent-backend"}`

### 前端启动

```bash
cd recollect
python -m http.server 8080 --directory frontend
```

验证：浏览器打开 `http://localhost:8080`

### 测试入口

| 入口 | 方式 |
|---|---|
| API | `POST http://127.0.0.1:8000/api/chat` |
| Web UI | `http://localhost:8080` → Sidebar "AI Assistant" |
| Context 入口 | Library → Knowledge → Detail → Ask Agent |
| 日志 | `data/conversations/conversations.jsonl` |
| Eval 记录 | `eval/agent/agent_runs.jsonl` |

### 测试数据

Supabase knowledge 表现有真实数据（如"陈数推荐的话梅台南实地店里购买"等，title 含"测试"的会被过滤）。可用真实 note_id 做 context 测试。

---

## 3. 核心功能验证 Checklist

### Case 1: 基于 Knowledge 的回答

**目的**：验证完整 RAG 链路。

**测试步骤**：
1. 打开 Web UI → AI Assistant
2. 输入一个与知识库相关的 query（如"总结一下这篇笔记的核心内容"）
3. 观察 response

**预期**：
- [ ] Agent 返回 answer（基于知识库内容）
- [ ] `metadata.router.should_inject = true`
- [ ] `metadata.context_applied = true`
- [ ] `sources` 返回对应 knowledge
- [ ] conversation log 新增一行（router_decision=true）

### Case 2: 普通 Chat Query

**目的**：验证无关 query 不强制注入 context。

**测试步骤**：
1. AI Assistant 输入与知识无关的问题（如"如何优化 React 组件性能？"）
2. 观察 response

**预期**：
- [ ] Router skip context（`should_inject=false`，`context_applied=false`）
- [ ] 返回普通通用回答（不引用知识库）
- [ ] 不出现错误的 source（sources 为空或为 retriever 空结果）
- [ ] conversation log 记录 router_decision=false

### Case 3: 指定 Knowledge Context

**目的**：验证带 knowledge_id 的 context 请求。

**测试方式**（API 层）：
```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"总结这个知识","context":{"knowledge_id":"<真实note_id>"}}'
```

**验证**：
- [ ] Context Resolver 读取指定 knowledge
- [ ] `metadata.context_knowledge_id` 正确返回
- [ ] 回答基于该知识内容

**说明**：Web UI 通过 Knowledge Detail → Ask Agent 触发相同请求（自动携带当前知识）。

### Case 4: 多轮对话

**目的**：验证 session_id 与 conversation log。

**测试步骤**：
1. 同一 session_id 连续发两条消息
2. 检查 conversation log

**预期**：
- [ ] 两次请求同 session_id 被记录
- [ ] memory 生效（user_memory.json 中的主题可影响回答）
- [ ] conversation log 两条记录，session_id 一致

> 注意：MVP 的 memory 仅读取 `user_memory.json`（需该文件存在），不含对话历史注入。

---

## 4. Context Router 验证

当前 Router V1：**lexical matching + intent signal**（无 embedding）。

### Related Query

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"总结这个知识","context":{"knowledge_id":"<真实note_id>"}}'
```

**预期**：`should_inject=true`，`score=1.0`（意图词"总结/这个知识"命中）。

### Irrelevant Query

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"如何优化 React 组件性能？","context":{"knowledge_id":"<真实note_id>"}}'
```

**预期**：`should_inject=false`，`score=0.0`（词面无重叠）。

### 记录表

| 测试项 | router.should_inject | router.score | router.reason |
|---|---|---|---|
| Related query | | | |
| Irrelevant query | | | |

---

## 5. Source Attribution 验证

### Response metadata 检查

```
POST /api/chat
Response:
{
  "answer": "...",
  "sources": [{note_id, title, url, category_l1, tldr}, ...],
  "metadata": {
    "session_id": "...",
    "context_applied": true/false,
    "context_knowledge_id": "...",
    "router": {should_inject, score, reason},
    "llm_provider": "deepseek",
    "token_usage": {...},
    "latency_ms": 0
  }
}
```

### 前端一致性

- [ ] 前端 source chips 显示的标题与 backend `sources[].title` 一致
- [ ] 前端 meta 行显示"基于知识回答"（当 router.should_inject=true 或 context_applied=true）
- [ ] 前端 meta 行显示"通用回答"（当带 context 请求但 router 跳过）
- [ ] token/latency/sources 数显示正确

---

## 6. Conversation Logging 验证

### 日志文件

`data/conversations/conversations.jsonl`（每轮一行 JSON）

### 字段检查

| 字段 | 说明 |
|---|---|
| `timestamp` | ISO 时间 |
| `session_id` | 会话 ID |
| `query` | 用户问题 |
| `answer_preview` | 回答前 200 字符 |
| `retrieved_context` | 请求是否带 knowledge context |
| `router_decision` | Router 是否注入（true/false/null）|
| `router_score` | Router 相似度分数 |
| `sources` | 引用的 note_id 列表 |
| `source_titles` | 引用标题（前 5）|
| `tokens` / `latency_ms` / `model` | 性能信息 |

### 验证

- [ ] 每次对话追加一行
- [ ] 字段完整且类型正确
- [ ] **失败不影响主流程**：即使日志写入失败（如目录不可写），Agent 回答仍正常返回
- [ ] 错误请求（empty query）也会记录

---

## 7. 已知限制（测试时不要误判）

以下为当前版本的已知限制，属于优化项，**不作为 bug 上报**：

1. **Retrieval miss**
   - retriever 是关键词打分（非语义检索）。
   - 意图式 query（无实体词，如"总结这个知识"）在 plain 模式下可能检索不到。
   - Context Injection 缓解此问题，但独立检索能力仍待优化。

2. **Knowledge coverage 不足**
   - Supabase knowledge 表仅少量真实数据。
   - 数据未覆盖的问题会得到"基于通用知识"的回答，或诚实说明无相关知识。

3. **Router V1 语义能力有限**
   - 使用 lexical + 意图词匹配，非 embedding。
   - 对"直接引用实体词但语义不相关"的边缘情况可能误判。
   - 未来升级方向：Embedding Similarity。

4. **Alpha 版本非完整产品**
   - 无认证、无多用户隔离。
   - 无 Analysis Skill / Supervisor Agent（计划后续阶段）。
   - Conversation log 仅为数据收集，无分析界面。

---

## 8. Bug Report Template

### 统一格式

```
Case:        <编号或简短描述>
Input:       <请求内容：query/session_id/context>
Expected:    <预期行为>
Actual:      <实际行为>
Router Decision: <should_inject / score / reason>
Source:      <引用的 sources 或为空>
Issue Type:  <见下方分类>
Priority:    <P0 阻塞 / P1 高 / P2 中 / P3 低>
Screenshot/Log: <截图或日志片段>
```

### Issue Type 分类

| 类型 | 说明 |
|---|---|
| Frontend | UI 显示、交互、source chips、meta 展示 |
| API | /api/chat 返回结构、状态码、请求处理 |
| Retrieval | 检索结果错误、漏检、误检 |
| Context Router | 注入决策错误（related 被跳过 / irrelevant 被注入）|
| Knowledge | 知识数据缺失、字段错误 |
| LLM Response | 回答质量、幻觉、拒答不当 |
| Logging | conversation log 缺失、字段错误 |

---

## 9. Demo Verification Checklist

一次完整 Demo 验证（Alpha MVP 全链路）：

### 准备
- [ ] 后端已启动（:8000），/health 返回 ok
- [ ] 前端已启动（:8080）
- [ ] Supabase 有真实 knowledge 数据
- [ ] LLM key 已配置

### 流程

| 步骤 | 操作 | 预期 | 通过 |
|---|---|---|---|
| 1 | 打开 `http://localhost:8080` | 加载工作台，Sidebar 可见 | ☐ |
| 2 | 点击 Sidebar → AI Assistant | 进入聊天页 | ☐ |
| 3 | 输入相关 query（如"总结这个知识"）| 显示回答 + source chips | ☐ |
| 4 | 观察 meta 行 | 含"基于知识回答"或来源数 | ☐ |
| 5 | 输入无关 query（如"如何优化 React"）| 正常通用回答，无错误 source | ☐ |
| 6 | 进入 Library → Knowledge → Detail | 查看知识详情页 | ☐ |
| 7 | 点击 Ask Agent | 跳转 AI Assistant，Context Panel 显示知识 | ☐ |
| 8 | 输入问题 | 回答基于该知识，meta 含"基于知识回答" | ☐ |
| 9 | 查看 `data/conversations/conversations.jsonl` | 每轮对话有日志记录 | ☐ |
| 10 | 查看 `eval/agent/agent_runs.jsonl` | 有 mode/context_applied 记录 | ☐ |

### 收尾
- [ ] 全部通过 → Alpha MVP 全链路正常
- [ ] 若有异常 → 用第 8 节模板记录 bug
