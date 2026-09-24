ALTER TABLE requests
ADD COLUMN execution_path TEXT
CHECK (
    execution_path IS NULL
    OR execution_path IN (
        'deterministic',
        'tool',
        'inference'
    )
);

CREATE TABLE tool_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
    tool TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    outcome TEXT CHECK (
        outcome IS NULL
        OR outcome IN ('succeeded', 'failed', 'cancelled')
    ),
    latency_ms INTEGER CHECK (
        latency_ms IS NULL OR latency_ms >= 0
    ),
    error_classification TEXT,
    FOREIGN KEY (request_id)
        REFERENCES requests(request_id)
        ON DELETE CASCADE,
    UNIQUE (request_id, attempt_index)
);

CREATE INDEX idx_tool_attempts_request_id
    ON tool_attempts(request_id);
