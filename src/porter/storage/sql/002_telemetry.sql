CREATE TABLE requests (
    request_id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL,
    source TEXT NOT NULL,
    session_id TEXT,
    task_type TEXT NOT NULL,
    privacy_class TEXT NOT NULL,
    allow_cloud INTEGER NOT NULL CHECK (allow_cloud IN (0, 1)),
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    route_reason TEXT,
    outcome TEXT CHECK (
        outcome IS NULL OR outcome IN ('succeeded', 'failed', 'cancelled')
    )
);

CREATE TABLE provider_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    outcome TEXT CHECK (
        outcome IS NULL OR outcome IN ('succeeded', 'failed', 'cancelled')
    ),
    latency_ms INTEGER CHECK (
        latency_ms IS NULL OR latency_ms >= 0
    ),
    input_tokens INTEGER CHECK (
        input_tokens IS NULL OR input_tokens >= 0
    ),
    output_tokens INTEGER CHECK (
        output_tokens IS NULL OR output_tokens >= 0
    ),
    estimated_cost_microusd INTEGER CHECK (
        estimated_cost_microusd IS NULL OR estimated_cost_microusd >= 0
    ),
    error_classification TEXT,
    FOREIGN KEY (request_id)
        REFERENCES requests(request_id)
        ON DELETE CASCADE,
    UNIQUE (request_id, attempt_index)
);

CREATE INDEX idx_provider_attempts_request_id
    ON provider_attempts(request_id);
