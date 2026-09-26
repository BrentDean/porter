-- Existing reminders remain reminders; timer deliveries retain the same claim/retry path.
ALTER TABLE reminders
    ADD COLUMN kind TEXT NOT NULL DEFAULT 'reminder'
    CHECK (kind IN ('reminder', 'timer'));

ALTER TABLE reminders
    ADD COLUMN duration_seconds INTEGER
    CHECK (duration_seconds IS NULL OR duration_seconds > 0);
