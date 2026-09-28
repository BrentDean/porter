ALTER TABLE requests
ADD COLUMN latency_ms INTEGER
CHECK (
    latency_ms IS NULL OR latency_ms >= 0
);
