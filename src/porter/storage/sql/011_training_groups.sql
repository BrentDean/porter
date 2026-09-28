CREATE TABLE training_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    handling TEXT NOT NULL
        CHECK (handling IN ('existing_behavior', 'new_deterministic', 'inference', 'discard')),
    target_label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (
        (handling = 'existing_behavior' AND target_label IS NOT NULL)
        OR (handling != 'existing_behavior' AND target_label IS NULL)
    )
);

ALTER TABLE training_examples
    ADD COLUMN group_id INTEGER REFERENCES training_groups(id) ON DELETE SET NULL;

CREATE INDEX idx_training_examples_group
    ON training_examples(group_id, id);
