from __future__ import annotations

import argparse

from porter.config.models import OllamaConfig, OpenAIConfig
from porter.config.store import ConfigStore


def _set_config(args: list[str]) -> int | None:
    if len(args) != 4 or args[:2] != ["config", "set"]:
        return None

    key = args[2]
    model = args[3].strip()
    store = ConfigStore()

    if key == "ollama.model":
        OllamaConfig(model=model)
        store.set_ollama_model(model)
    elif key == "openai.model":
        OpenAIConfig(model=model)
        store.set_openai_model(model)
    else:
        return None

    print(f"Saved {key}={model} to {store.path}")
    return 0


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter config",
        description="Manage Porter configuration",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)
    set_parser = subparsers.add_parser("set", help="set a configuration value")
    set_parser.add_argument("key", choices=("ollama.model", "openai.model"))
    set_parser.add_argument("value")
    parsed = parser.parse_args(args)

    result = _set_config(["config", parsed.action, parsed.key, parsed.value])
    if result is None:
        raise AssertionError("parsed configuration command was not handled")
    return result
