CREATE TABLE training_examples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    label TEXT,
    review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'reviewed', 'promoted')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_training_examples_session
    ON training_examples(session_id, id);

CREATE INDEX idx_training_examples_review
    ON training_examples(review_status, id);

CREATE INDEX idx_training_examples_normalized
    ON training_examples(normalized_text);

CREATE TABLE recognition_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_text TEXT NOT NULL UNIQUE,
    latest_raw_text TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 0 CHECK (occurrence_count >= 0),
    ai_approved_count INTEGER NOT NULL DEFAULT 0 CHECK (ai_approved_count >= 0),
    ai_declined_count INTEGER NOT NULL DEFAULT 0 CHECK (ai_declined_count >= 0),
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_recognition_gaps_frequency
    ON recognition_gaps(occurrence_count DESC, last_seen_at DESC);
