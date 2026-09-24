from __future__ import annotations

import argparse
import asyncio
import sys
from shutil import which

from porter.cache import InferenceCache
from porter.config.loader import ConfigLoader
from porter.providers.ollama import OllamaClient, OllamaClientError
from porter.storage.database import Database


def _ollama_model_names(payload: dict[str, object]) -> set[str]:
    models = payload.get("models")
    if not isinstance(models, list):
        return set()

    names: set[str] = set()
    for entry in models:
        if not isinstance(entry, dict):
            continue
        for key in ("name", "model"):
            candidate = entry.get(key)
            if isinstance(candidate, str):
                names.add(candidate.removesuffix(":latest"))
    return names


async def _run_doctor(loader: ConfigLoader | None = None) -> int:
    config_loader = loader or ConfigLoader()
    config = config_loader.load()

    print("Porter doctor")
    print()
    print("Configuration")
    print(f"  file: {config_loader.config_path}")
    print()
    print("Ollama")
    print(f"  configured: {'yes' if config.ollama.model is not None else 'no'}")
    print(f"  model: {config.ollama.model or '<not configured>'}")
    print(f"  endpoint: {config.ollama.base_url}")

    client = OllamaClient(config.ollama)
    try:
        payload = await client.list_models()
    except OllamaClientError:
        print("  server: unavailable")
        print("  model installed: unknown")
        print("  status: unavailable")
    else:
        print("  server: available")
        if config.ollama.model is None:
            print("  model installed: n/a")
            print("  status: not configured")
        else:
            configured_model = config.ollama.model.removesuffix(":latest")
            installed = configured_model in _ollama_model_names(payload)
            print(f"  model installed: {'yes' if installed else 'no'}")
            print(f"  status: {'healthy' if installed else 'model missing'}")

    print()
    print("OpenAI cloud fallback")
    print(f"  model: {config.openai.model or '<not configured>'}")
    print(f"  API key: {'configured' if config.openai.api_key is not None else 'missing'}")
    if config.openai.configured:
        print("  status: ready (explicit --allow-cloud required)")
    elif config.openai.model is not None:
        print("  status: API key missing")
    elif config.openai.api_key is not None:
        print("  status: model not configured")
    else:
        print("  status: disabled")

    print()
    print("Local tools")
    for name in ("qalc", "lsblk", "df"):
        print(f"  {name}: {'available' if which(name) is not None else 'missing'}")

    print()
    print("Inference cache")
    try:
        cache = InferenceCache(Database(config.storage.database_path))
        stats = cache.stats()
    except Exception:
        print("  status: unavailable")
    else:
        print("  status: available")
        print(f"  entries: {stats.entries}")
        print(f"  hits: {stats.hits}")
        print(f"  misses: {stats.misses}")

    return 0


async def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="porter doctor",
        description="Check Porter local configuration and dependencies",
    )
    parser.parse_args(args)
    return await _run_doctor()


def main() -> None:
    try:
        exit_code = asyncio.run(run(sys.argv[1:]))
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
