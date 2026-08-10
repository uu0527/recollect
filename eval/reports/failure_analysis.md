# Failure Analysis (Phase 3.4a)

> 自动生成，基于 benchmark + stability 结果。

## 总览
- 失败 case 总数: 45
- leakage: 0
- retriever_miss: 41
- injection_failure: 4
- judge_disagreement: 0

## leakage: Dataset leakage（query 泄露 title/key_points）
- 无

## retriever_miss: Retriever miss（plain 模式检索不到预期知识）
- `69058a8e0000_summary_713`: {"id": "69058a8e0000_summary_713", "query": "这篇笔记大概讲了什么？", "relevance": 1}
- `69058a8e0000_source_grounding_304`: {"id": "69058a8e0000_source_grounding_304", "query": "这个知识具体有哪些关键信息？", "relevance": 1}
- `69058a8e0000_decision_support_280`: {"id": "69058a8e0000_decision_support_280", "query": "这个信息对我做决定有帮助吗？", "relevance": 1}
- `69058a8e0000_decision_support_654`: {"id": "69058a8e0000_decision_support_654", "query": "基于这个知识，我该从哪入手？", "relevance": 1}
- `69058a8e0000_knowledge_exploration_33`: {"id": "69058a8e0000_knowledge_exploration_33", "query": "关于这个话题还有哪些细节？", "relevance": 1}
- `69058a8e0000_knowledge_exploration_983`: {"id": "69058a8e0000_knowledge_exploration_983", "query": "想多了解下这个知识", "relevance": 1}
- `67fdfd140000_summary_790`: {"id": "67fdfd140000_summary_790", "query": "帮我看看这篇内容说了什么", "relevance": 1}
- `67fdfd140000_summary_195`: {"id": "67fdfd140000_summary_195", "query": "能简单概括下这个知识吗？", "relevance": 1}
- `67fdfd140000_source_grounding_184`: {"id": "67fdfd140000_source_grounding_184", "query": "这个知识里有哪些具体的点？", "relevance": 1}
- `67fdfd140000_decision_support_680`: {"id": "67fdfd140000_decision_support_680", "query": "这个知识有什么参考价值？", "relevance": 1}
- ... 共 41 条

## injection_failure: Context injection failure（未注入或注入无提升）
- `69058a8e0000_source_grounding_304`: {"id": "69058a8e0000_source_grounding_304", "plain_rel": 1, "ctx_rel": 1, "query": "这个知识具体有哪些关键信息？"}
- `690490770000_knowledge_exploration_239`: {"id": "690490770000_knowledge_exploration_239", "plain_rel": 2, "ctx_rel": 2, "query": "这个话题的背景是什么？"}
- `6a4f80be0000_summary_718`: {"id": "6a4f80be0000_summary_718", "plain_rel": 2, "ctx_rel": 2, "query": "帮我总结一下这篇笔记的核心内容"}
- `68da9afb0000_knowledge_exploration_239`: {"id": "68da9afb0000_knowledge_exploration_239", "plain_rel": 2, "ctx_rel": 2, "query": "这个话题的背景是什么？"}

## judge_disagreement: Judge disagreement（多次评分方差过大）
- 无

## 后续建议
- 若 retriever_miss 高: 说明 Context Injection 价值最大，应优先保障注入路径
- 若 leakage 高: 需加强 generate_cases 的 validate_leakage
- 若 injection_failure 高: 检查 orchestrator._resolve_context 的 fallback 分支