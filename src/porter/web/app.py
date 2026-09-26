from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, field_validator

from porter.app import PorterApplication, build_application
from porter.app.inference import InferenceDecision
from porter.conversation import ConversationSession
from porter.core.exceptions import (
    ActionNotAuthorized,
    InferenceConfirmationRequired,
    InferenceDeclined,
    NoProviderAvailable,
)
from porter.core.models import ExecutionPath, Message, RequestContext, RequestSource

_FRONTEND_DIR = Path(__file__).with_name("frontend")
_FRONTEND_PATHS = {"/", "/index.html", "/app.js", "/styles.css"}


class HealthResponse(BaseModel):
    status: str


class WebRequest(BaseModel):
    text: str
    session_id: str | None = None
    allow_inference: bool | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("session_id must not be empty when provided")
        return value


class WebRequestResult(BaseModel):
    request_id: str
    text: str
    path: ExecutionPath
    provider: str | None = None
    model: str | None = None
    tool: str | None = None
    data: dict[str, Any]


def _error_response(*, status_code: int, error: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": error, "detail": detail},
    )


def _inference_decision(allow_inference: bool | None) -> InferenceDecision:
    if allow_inference is None:
        return InferenceDecision.UNSPECIFIED
    if allow_inference:
        return InferenceDecision.APPROVED
    return InferenceDecision.DECLINED


def create_web_app(application: PorterApplication | None = None) -> FastAPI:
    porter = application or build_application()
    sessions: dict[str, ConversationSession] = {}
    app = FastAPI(
        title="Porter API",
        version="0.1.0",
        description="Local HTTP boundary for the Porter control plane.",
    )

    @app.middleware("http")
    async def disable_frontend_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path in _FRONTEND_PATHS:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ActionNotAuthorized)
    async def action_not_authorized(
        _request: Request,
        exc: ActionNotAuthorized,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_403_FORBIDDEN,
            error="action_not_authorized",
            detail=str(exc),
        )

    @app.exception_handler(InferenceConfirmationRequired)
    async def inference_confirmation_required(
        _request: Request,
        exc: InferenceConfirmationRequired,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_409_CONFLICT,
            error="inference_confirmation_required",
            detail=str(exc),
        )

    @app.exception_handler(InferenceDeclined)
    async def inference_declined(
        _request: Request,
        exc: InferenceDeclined,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_409_CONFLICT,
            error="inference_declined",
            detail=str(exc),
        )

    @app.exception_handler(NoProviderAvailable)
    async def no_provider_available(
        _request: Request,
        exc: NoProviderAvailable,
    ) -> JSONResponse:
        return _error_response(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            error="no_provider_available",
            detail=str(exc),
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.get("/readyz", response_model=HealthResponse)
    async def readyz() -> HealthResponse | JSONResponse:
        try:
            ready = porter.database.healthcheck()
        except Exception:
            ready = False

        if not ready:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"status": "unavailable"},
            )
        return HealthResponse(status="ready")

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(
            content=generate_latest(porter.metrics_registry),
            headers={"Content-Type": CONTENT_TYPE_LATEST},
        )

    @app.post("/api/v1/requests", response_model=WebRequestResult)
    async def execute_request(payload: WebRequest) -> WebRequestResult:
        session = None
        messages = (Message(role="user", content=payload.text),)
        if payload.session_id is not None:
            session = sessions.setdefault(
                payload.session_id,
                ConversationSession(session_id=payload.session_id),
            )
            messages = session.messages_for(payload.text)

        request = RequestContext(
            messages=messages,
            principal_id="local-user",
            source=RequestSource.WEB,
            session_id=payload.session_id,
        )
        decision = _inference_decision(payload.allow_inference)
        result = await porter.dispatcher.execute(
            request,
            inference_decider=lambda _request: decision,
        )
        if session is not None:
            session.record_turn(payload.text, result.text)
        return WebRequestResult(
            request_id=request.request_id,
            text=result.text,
            path=result.path,
            provider=result.provider,
            model=result.model,
            tool=result.tool,
            data=jsonable_encoder(dict(result.data)),
        )

    @app.delete("/api/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def clear_session(session_id: str) -> None:
        sessions.pop(session_id, None)

    app.frontend("/", directory=_FRONTEND_DIR, fallback=None)
    return app
