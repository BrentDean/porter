CREATE TABLE reminders (
    id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL CHECK (length(trim(principal_id)) > 0),
    message TEXT NOT NULL CHECK (length(trim(message)) > 0),
    status TEXT NOT NULL
        CHECK (status IN ('scheduled', 'delivered', 'cancelled')),
    trigger_at_utc TEXT NOT NULL,
    trigger_timezone TEXT NOT NULL CHECK (length(trim(trigger_timezone)) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT,
    cancelled_at TEXT,
    CHECK (
        (status = 'scheduled' AND delivered_at IS NULL AND cancelled_at IS NULL)
        OR
        (status = 'delivered' AND delivered_at IS NOT NULL AND cancelled_at IS NULL)
        OR
        (status = 'cancelled' AND delivered_at IS NULL AND cancelled_at IS NOT NULL)
    )
);

CREATE INDEX idx_reminders_principal_status
    ON reminders(principal_id, status);

CREATE INDEX idx_reminders_due
    ON reminders(status, trigger_at_utc);
