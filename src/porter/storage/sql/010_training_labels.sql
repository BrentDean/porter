ALTER TABLE training_examples
    ADD COLUMN route_type TEXT
        CHECK (route_type IN ('deterministic', 'inference', 'needs_review', 'discard'));

ALTER TABLE training_examples
    ADD COLUMN reviewed_at TEXT;

CREATE INDEX idx_training_examples_route
    ON training_examples(route_type, review_status, id);
