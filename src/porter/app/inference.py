from __future__ import annotations

import logging
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from porter.core.exceptions import InferenceConfirmationRequired, InferenceDeclined
from porter.core.models import RequestContext
from porter.telemetry.structured_logging import emit_event


class InferenceDecision(StrEnum):
    UNSPECIFIED = "unspecified"
    APPROVED = "approved"
    DECLINED = "declined"


InferenceDecider = Callable[[RequestContext], InferenceDecision]


class RecognitionGapRecorder(Protocol):
    def record(self, *, raw_text: str, ai_approved: bool) -> object: ...


class InferenceGate:
    """Owns explicit inference approval and best-effort recognition-gap feedback."""

    def __init__(self, recorder: RecognitionGapRecorder | None = None) -> None:
        self._recorder = recorder

    def require_approval(
        self,
        request: RequestContext,
        decision: InferenceDecision,
    ) -> None:
        if decision is InferenceDecision.UNSPECIFIED:
            if request.allow_cloud:
                raise InferenceConfirmationRequired(
                    "cloud inference requires explicit approval"
                )
            # Local-only inference is the default. Preserve the explicit
            # decision boundary for any request that permits cloud execution.
            decision = InferenceDecision.APPROVED

        self._record_recognition_gap(request, decision)

        if decision is InferenceDecision.DECLINED:
            raise InferenceDeclined("local AI inference was declined")

    def _record_recognition_gap(
        self,
        request: RequestContext,
        decision: InferenceDecision,
    ) -> None:
        if self._recorder is None:
            return

        text = request.latest_user_text
        if text is None:
            return

        try:
            self._recorder.record(
                raw_text=text,
                ai_approved=decision is InferenceDecision.APPROVED,
            )
        except Exception as exc:
            emit_event(
                "recognition_gap.persistence_failed",
                level=logging.WARNING,
                error_classification=type(exc).__name__,
            )
