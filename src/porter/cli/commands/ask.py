from __future__ import annotations

import argparse
import sys

from porter.app import PorterApplication, build_application
from porter.app.inference import InferenceDecision
from porter.conversation import ConversationSession
from porter.core.exceptions import InferenceDeclined, NoProviderAvailable
from porter.core.models import (
    ExecutionPath,
    Message,
    PrivacyClass,
    RequestContext,
    RequestResult,
    RequestSource,
)


def _build_request(
    text: str,
    *,
    allow_cloud: bool = False,
    conversation: ConversationSession | None = None,
) -> RequestContext:
    messages = (
        conversation.messages_for(text)
        if conversation is not None
        else (Message(role="user", content=text),)
    )
    return RequestContext(
        messages=messages,
        principal_id="local-user",
        source=RequestSource.CLI,
        session_id=(conversation.session_id if conversation is not None else None),
        privacy_class=(
            PrivacyClass.CLOUD_ALLOWED if allow_cloud else PrivacyClass.LOCAL_ONLY
        ),
        allow_cloud=allow_cloud,
    )


def _route_label(result: RequestResult) -> str:
    if result.path is ExecutionPath.DETERMINISTIC:
        return "deterministic"
    if result.path is ExecutionPath.TOOL and result.tool is not None:
        return f"tool: {result.tool}"
    if result.provider is not None and result.model is not None:
        return f"inference: {result.provider}/{result.model}"
    return "inference"


def _confirm_inference(request: RequestContext) -> InferenceDecision:
    if not request.allow_cloud:
        return InferenceDecision.APPROVED

    prompt = (
        "No deterministic match. Press Enter to allow local AI with cloud "
        "fallback for this request, or type n to cancel: "
    )
    retry = "Please press Enter to allow cloud fallback, or type n to cancel."

    while True:
        try:
            response = input(prompt).strip().casefold()
        except (EOFError, KeyboardInterrupt):
            print()
            return InferenceDecision.DECLINED

        if response == "":
            return InferenceDecision.APPROVED
        if response in {"n", "no"}:
            return InferenceDecision.DECLINED
        print(retry)


def _confirm_local_inference(request: RequestContext) -> InferenceDecision:
    """Compatibility wrapper for the pre-cloud CLI confirmation helper."""
    return _confirm_inference(request)


def _provider_unavailable_message(
    application: PorterApplication,
    exc: NoProviderAvailable,
) -> str:
    providers = application.provider_registry.all()
    if (
        application.config.ollama.model is None
        and not any(not provider.is_cloud for provider in providers)
    ):
        return (
            "no local AI model is configured; run "
            "`porter config set ollama.model <model>`"
        )

    provider_names = {provider.name for provider in providers}
    if "ollama" in provider_names and str(exc).startswith("ollama:"):
        return "Ollama inference failed; run `porter doctor` for details"
    return str(exc)


def _print_provider_unavailable(
    application: PorterApplication,
    exc: NoProviderAvailable,
) -> None:
    print(f"porter: {_provider_unavailable_message(application, exc)}", file=sys.stderr)


async def _execute(
    application: PorterApplication,
    text: str,
    *,
    allow_cloud: bool = False,
    conversation: ConversationSession | None = None,
) -> RequestResult:
    result = await application.dispatcher.execute(
        _build_request(
            text,
            allow_cloud=allow_cloud,
            conversation=conversation,
        ),
        inference_decider=_confirm_inference,
    )
    if conversation is not None:
        conversation.record_turn(text, result.text)
    print(result.text)
    print(f"[{_route_label(result)}]")
    return result


async def execute_text(
    application: PorterApplication,
    text: str,
    *,
    allow_cloud: bool = False,
    conversation: ConversationSession | None = None,
) -> int:
    try:
        await _execute(
            application,
            text,
            allow_cloud=allow_cloud,
            conversation=conversation,
        )
    except InferenceDeclined:
        print("AI request cancelled.")
        return 0
    except NoProviderAvailable as exc:
        _print_provider_unavailable(application, exc)
        return 1
    return 0


async def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter ask",
        description="Run one Porter request",
    )
    parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="explicitly permit cloud inference fallback for this request",
    )
    parser.add_argument("prompt", nargs="+", help="request text")
    parsed = parser.parse_args(args)
    return await execute_text(
        build_application(),
        " ".join(parsed.prompt),
        allow_cloud=parsed.allow_cloud,
    )
