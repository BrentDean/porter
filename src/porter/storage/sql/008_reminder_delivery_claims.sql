CREATE TABLE reminders_v8 (
    id TEXT PRIMARY KEY,
    principal_id TEXT NOT NULL CHECK (length(trim(principal_id)) > 0),
    message TEXT NOT NULL CHECK (length(trim(message)) > 0),
    status TEXT NOT NULL
        CHECK (status IN ('scheduled', 'delivering', 'delivered', 'cancelled')),
    trigger_at_utc TEXT NOT NULL,
    trigger_timezone TEXT NOT NULL CHECK (length(trim(trigger_timezone)) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT,
    cancelled_at TEXT,
    delivery_attempt_count INTEGER NOT NULL DEFAULT 0
        CHECK (delivery_attempt_count >= 0),
    next_delivery_attempt_at_utc TEXT,
    delivery_claimed_at_utc TEXT,
    CHECK (
        (
            status = 'scheduled'
            AND delivered_at IS NULL
            AND cancelled_at IS NULL
            AND delivery_claimed_at_utc IS NULL
        )
        OR
        (
            status = 'delivering'
            AND delivered_at IS NULL
            AND cancelled_at IS NULL
            AND delivery_claimed_at_utc IS NOT NULL
        )
        OR
        (
            status = 'delivered'
            AND delivered_at IS NOT NULL
            AND cancelled_at IS NULL
            AND delivery_claimed_at_utc IS NULL
        )
        OR
        (
            status = 'cancelled'
            AND delivered_at IS NULL
            AND cancelled_at IS NOT NULL
            AND delivery_claimed_at_utc IS NULL
        )
    )
);

INSERT INTO reminders_v8 (
    id,
    principal_id,
    message,
    status,
    trigger_at_utc,
    trigger_timezone,
    created_at,
    updated_at,
    delivered_at,
    cancelled_at,
    delivery_attempt_count,
    next_delivery_attempt_at_utc,
    delivery_claimed_at_utc
)
SELECT
    id,
    principal_id,
    message,
    status,
    trigger_at_utc,
    trigger_timezone,
    created_at,
    updated_at,
    delivered_at,
    cancelled_at,
    delivery_attempt_count,
    next_delivery_attempt_at_utc,
    NULL
FROM reminders;

DROP TABLE reminders;
ALTER TABLE reminders_v8 RENAME TO reminders;

CREATE INDEX idx_reminders_principal_status
    ON reminders(principal_id, status);

CREATE INDEX idx_reminders_due
    ON reminders(status, trigger_at_utc);

CREATE INDEX idx_reminders_delivery_ready
    ON reminders(status, trigger_at_utc, next_delivery_attempt_at_utc);

CREATE INDEX idx_reminders_delivery_claim
    ON reminders(status, delivery_claimed_at_utc);
