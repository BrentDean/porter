from __future__ import annotations

import sys
from difflib import get_close_matches

from porter.app import PorterApplication
from porter.cli.commands.ask import execute_text
from porter.cli.commands.doctor import _run_doctor
from porter.cli.commands.training import (
    _print_training_groups,
    _run_training_review,
    _run_training_session,
)
from porter.conversation import ConversationSession

_REPL_HELP = """Porter command examples

Storage
  which drives are mounted
  which drives are unmounted
  show my drives
  show storage layout
  disk usage
  which drives are almost full

Plex
  start plex
  stop plex
  restart plex

Memory
  remember that my favorite number is 12
  what do you remember about me
  forget that my favorite number is 12

Training
  training
  training review
  training groups

Diagnostics
  doctor

Session
  clear context
  help
  exit
  quit

You can also enter normal Porter requests in this prompt.
"""

_SUGGESTION_COMMANDS = (
    "which drives are mounted",
    "which drives are unmounted",
    "show my drives",
    "show storage layout",
    "disk usage",
    "which drives are almost full",
    "start plex",
    "stop plex",
    "restart plex",
    "what do you remember about me",
    "training",
    "training review",
    "training groups",
    "doctor",
    "clear context",
    "help",
    "exit",
    "quit",
)
_SUGGESTION_CUTOFF = 0.90


def _normalize_command(text: str) -> str:
    return " ".join(text.casefold().split())


def _suggest_command(text: str) -> str | None:
    normalized = _normalize_command(text)
    commands_by_normalized = {
        _normalize_command(command): command for command in _SUGGESTION_COMMANDS
    }
    if normalized in commands_by_normalized:
        return None

    matches = get_close_matches(
        normalized,
        tuple(commands_by_normalized),
        n=1,
        cutoff=_SUGGESTION_CUTOFF,
    )
    if not matches:
        return None
    return commands_by_normalized[matches[0]]


def _print_repl_help() -> None:
    print(_REPL_HELP.rstrip())


def _print_suggestion(text: str) -> bool:
    suggestion = _suggest_command(text)
    if suggestion is None:
        return False

    print(
        f"porter: command not recognized. Did you mean: {suggestion}",
        file=sys.stderr,
    )
    return True


async def _run_once(application: PorterApplication, text: str) -> int:
    normalized = _normalize_command(text)
    if normalized == "help":
        _print_repl_help()
        return 0
    if normalized == "training":
        return _run_training_session(application)
    if normalized == "training review":
        return _run_training_review(application)
    if normalized == "training groups":
        _print_training_groups(application)
        return 0
    if normalized == "doctor":
        return await _run_doctor()
    if _print_suggestion(text):
        return 1
    return await execute_text(application, text)


async def _run_repl(application: PorterApplication) -> int:
    conversation = ConversationSession()

    while True:
        try:
            text = input("porter> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not text:
            continue

        normalized = _normalize_command(text)
        if normalized in {"exit", "quit", "exit()", "quit()"}:
            return 0
        if normalized in {"help", "?"}:
            _print_repl_help()
            continue
        if normalized == "clear context":
            conversation.clear()
            print("Conversation context cleared.")
            continue
        if normalized == "training":
            _run_training_session(application)
            continue
        if normalized == "training review":
            _run_training_review(application)
            continue
        if normalized == "training groups":
            _print_training_groups(application)
            continue
        if normalized == "doctor":
            await _run_doctor()
            continue
        if _print_suggestion(text):
            continue
        await execute_text(application, text, conversation=conversation)
