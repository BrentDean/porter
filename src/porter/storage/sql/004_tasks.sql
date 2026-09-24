CREATE TABLE task_lists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    name_key TEXT NOT NULL UNIQUE,
    position INTEGER NOT NULL CHECK (position >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_task_lists_position
    ON task_lists(position);

CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    list_id TEXT NOT NULL,
    summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
    description TEXT,
    status TEXT NOT NULL
        CHECK (status IN ('needs_action', 'completed')),
    priority INTEGER NOT NULL DEFAULT 0
        CHECK (priority BETWEEN 0 AND 9),
    due_date TEXT,
    due_at_utc TEXT,
    due_timezone TEXT,
    position INTEGER NOT NULL CHECK (position >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (list_id)
        REFERENCES task_lists(id)
        ON DELETE RESTRICT,
    CHECK (NOT (due_date IS NOT NULL AND due_at_utc IS NOT NULL)),
    CHECK (
        (due_at_utc IS NULL AND due_timezone IS NULL)
        OR
        (due_at_utc IS NOT NULL AND due_timezone IS NOT NULL)
    )
);

CREATE INDEX idx_tasks_list_position
    ON tasks(list_id, position);

CREATE INDEX idx_tasks_status
    ON tasks(status);

CREATE INDEX idx_tasks_due_date
    ON tasks(due_date);

CREATE INDEX idx_tasks_due_at_utc
    ON tasks(due_at_utc);
