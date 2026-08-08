-- ============================================================
-- ReCollect Supabase Schema（Alpha MVP P0）
-- 表: events / knowledge
-- 在 Supabase SQL Editor 中执行此文件
-- ============================================================

-- ------------------------------------------------------------
-- events：原始浏览器事件（note_view / note_collect）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,                 -- note_view | note_collect
    note_id     TEXT,
    url         TEXT,
    title       TEXT,
    content     TEXT,
    images      JSONB DEFAULT '[]',
    author      TEXT,
    payload     JSONB DEFAULT '{}',            -- 完整原始事件（审计追溯）
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_events_note_id    ON events (note_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at DESC);

-- ------------------------------------------------------------
-- knowledge：知识卡片（核心产出，Web 展示主数据）
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge (
    id            BIGSERIAL PRIMARY KEY,
    note_id       TEXT UNIQUE NOT NULL,        -- 幂等键
    title         TEXT,
    url           TEXT,
    category_l1   TEXT,
    category_l2   TEXT,
    tags          JSONB DEFAULT '[]',
    tldr          TEXT,
    key_points    JSONB DEFAULT '[]',
    actionable    TEXT,
    content_type  TEXT,                        -- 图文 | 视频
    raw_content   TEXT,                        -- 原文正文
    images        JSONB DEFAULT '[]',
    quality_flags JSONB DEFAULT '[]',
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- 常用查询索引
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge (category_l1);
CREATE INDEX IF NOT EXISTS idx_knowledge_created  ON knowledge (created_at DESC);

-- 说明：upsert 用法
--   INSERT INTO knowledge (...) VALUES (...)
--   ON CONFLICT (note_id) DO UPDATE SET title=EXCLUDED.title, updated_at=now();
-- 或通过 supabase-py: table('knowledge').upsert(row, on_conflict='note_id')
