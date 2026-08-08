CREATE TABLE IF NOT EXISTS events (
    id          BIGSERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    note_id     TEXT,
    url         TEXT,
    title       TEXT,
    content     TEXT,
    images      JSONB DEFAULT '[]',
    author      TEXT,
    payload     JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_note_id    ON events (note_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events (created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge (
    id            BIGSERIAL PRIMARY KEY,
    note_id       TEXT UNIQUE NOT NULL,
    title         TEXT,
    url           TEXT,
    category_l1   TEXT,
    category_l2   TEXT,
    tags          JSONB DEFAULT '[]',
    tldr          TEXT,
    key_points    JSONB DEFAULT '[]',
    actionable    TEXT,
    content_type  TEXT,
    raw_content   TEXT,
    images        JSONB DEFAULT '[]',
    quality_flags JSONB DEFAULT '[]',
    created_at    TIMESTAMPTZ DEFAULT now(),
    updated_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge (category_l1);
CREATE INDEX IF NOT EXISTS idx_knowledge_created  ON knowledge (created_at DESC);
