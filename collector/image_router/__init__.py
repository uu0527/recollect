"""
Image Router（MVP）— Vision 前置图片价值筛选层

职责：
  在进入 Vision 前对 RawNote.images 做价值筛选，生成 selected_images，
  降低 token 成本，同时保留高信息图片（长图文/知识卡片）。

  不修改 RawNote 原始 images；不引入 OCR / Embedding / 额外模型。

用法：
  from collector.image_router import select_images
  selected = select_images(note.images, metadata_provider=fetch_meta)
"""
from collector.image_router.scorer import score_image
from collector.image_router.selector import (
    MAX_NORMAL,
    MAX_SELECT,
    select_images,
    select_images_simple,
)

__all__ = [
    "score_image",
    "select_images",
    "select_images_simple",
    "MAX_NORMAL",
    "MAX_SELECT",
]
