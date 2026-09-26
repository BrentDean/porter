ALTER TABLE reminders
    ADD COLUMN delivery_attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (delivery_attempt_count >= 0);

ALTER TABLE reminders
    ADD COLUMN next_delivery_attempt_at_utc TEXT;

CREATE INDEX idx_reminders_delivery_ready
    ON reminders(status, trigger_at_utc, next_delivery_attempt_at_utc);
