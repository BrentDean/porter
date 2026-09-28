from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


def normalize_training_text(text: str) -> str:
    """Normalize training text for grouping without changing the stored raw phrase."""
    return " ".join(text.casefold().split())


class TrainingRouteType(StrEnum):
    DETERMINISTIC = "deterministic"
    INFERENCE = "inference"
    NEEDS_REVIEW = "needs_review"
    DISCARD = "discard"


class TrainingGroupHandling(StrEnum):
    EXISTING_BEHAVIOR = "existing_behavior"
    NEW_DETERMINISTIC = "new_deterministic"
    INFERENCE = "inference"
    DISCARD = "discard"


@dataclass(frozen=True, slots=True)
class TrainingExample:
    id: int
    session_id: str
    raw_text: str
    normalized_text: str
    label: str | None
    route_type: TrainingRouteType | None
    group_id: int | None
    review_status: str
    created_at: str
    reviewed_at: str | None


@dataclass(frozen=True, slots=True)
class TrainingGroup:
    id: int
    name: str
    handling: TrainingGroupHandling
    target_label: str | None
    example_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class TrainingReviewSummary:
    ungrouped: int
    grouped: int
    groups: int
    promoted: int


@dataclass(frozen=True, slots=True)
class RecognitionGap:
    id: int
    normalized_text: str
    latest_raw_text: str
    occurrence_count: int
    ai_approved_count: int
    ai_declined_count: int
    first_seen_at: str
    last_seen_at: str
