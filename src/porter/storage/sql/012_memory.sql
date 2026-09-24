CREATE TABLE memory_facts (
    id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_key TEXT NOT NULL,
    provenance_source TEXT NOT NULL,
    provenance_session_id TEXT,
    provenance_request_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(principal_id, content_key)
);

CREATE INDEX idx_memory_facts_principal_updated
ON memory_facts(principal_id, updated_at DESC);
