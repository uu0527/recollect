# Image Router Eval

ReCollect 第一个 AI Eval Harness（离线评估）。

## 目的

持续评估 Image Router 对 Vision pipeline 的影响，回答 3 个问题：
1. 是否降低 Vision 成本？（Reduction Rate / Token Saving）
2. 是否保留关键图片信息？（长图/高分图保留检查）
3. 是否导致 summary 质量下降？（MVP 暂用规则替代 LLM Judge）

## 目录

```
eval/image_router/
    cases.json     # 评估用例定义
    runner.py      # 执行入口
    metrics.py     # 指标计算（离线、规则驱动）
    results.json   # 运行结果（自动生成）
```

## 执行

```bash
cd D:\Users\aimee.yu\Documents\trae_projects\knowledge\recollect
python eval/image_router/runner.py            # 全部 case
python eval/image_router/runner.py --case real_xiaohongshu_summer_outfit  # 单个
```

## 指标

| 指标 | 公式 | 说明 |
|---|---|---|
| Image Reduction Rate | `1 - after/before` | 图片压缩率 |
| Token Saving Estimate | `(before-after) × 1500` | 每图 ~1500 input token（实测） |
| Information Preservation | 规则检查 | 长图保留 / 高分图保留 / 知识图排序 |

## Case 结构

```json
{
  "case_id": "real_xiaohongshu_summer_outfit",
  "note_id": "6a7692b10000000033011882",
  "image_count_before": 12,
  "expected_max_images": 6,
  "expected_keep_patterns": ["long_image"],
  "source": "real_events_20260808"
}
```

- `source=real_*`：从 `data/01_raw/` 加载真实笔记图片（webp 头解析尺寸）
- `source=synthetic`：按 `image_spec` 合成（长图/普通/重复/封面）

## 未来扩展

- Summary quality eval（LLM Judge）
- Hallucination eval
- Memory retrieval eval
