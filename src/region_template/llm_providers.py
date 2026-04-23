"""Provider map + model-string resolution (spec §C.9, §C.10, §C.14).

Responsibilities:

- :data:`SUPPORTED_PROVIDERS` — the closed set of provider strings accepted
  by the adapter (spec §C.9 table).
- :data:`PROVIDER_REQUIRED_ENV` — env var names that must be set at adapter
  bootstrap for each provider (spec §C.10).
- :func:`validate_provider_env` — raise :class:`ConfigError` on missing env
  or unknown provider.
- :func:`resolve_model_string` — turn the region's ``llm.model`` into the
  model string passed to ``litellm.acompletion``. If a
  ``litellm.config.yaml`` with a matching entry in ``model_list`` exists, we
  pass the region's model name through verbatim (LiteLLM's Router resolves
  it). Otherwise we return ``f"{provider}/{model}"`` per LiteLLM's
  provider-prefix convention.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from region_template.config_loader import LlmConfig
from region_template.errors import ConfigError

__all__ = [
    "PROVIDER_REQUIRED_ENV",
    "SUPPORTED_PROVIDERS",
    "resolve_model_string",
    "validate_provider_env",
]


SUPPORTED_PROVIDERS: frozenset[str] = frozenset(
    {
        "anthropic",
        "bedrock",
        "openai",
        "azure",
        "google",
        "ollama",
        "vllm",
        "groq",
    }
)


# Env var names the provider requires at bootstrap.
# An empty tuple means no env var is strictly required (e.g. ollama reads
# OLLAMA_API_BASE but defaults to http://localhost:11434; vllm takes its
# endpoint via params).
PROVIDER_REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "anthropic": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "bedrock": ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"),
    "azure": ("AZURE_API_KEY", "AZURE_API_BASE"),
    "google": ("GOOGLE_APPLICATION_CREDENTIALS",),
    "ollama": (),
    "vllm": (),
    "groq": ("GROQ_API_KEY",),
}


def validate_provider_env(provider: str) -> None:
    """Raise :class:`ConfigError` if ``provider`` is unknown or env incomplete.

    Called once per adapter ``__init__``. Surfaces as exit 2 via the caller's
    error handler (spec §C.16).
    """
    if provider not in SUPPORTED_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_PROVIDERS))
        raise ConfigError(
            f"unknown LLM provider '{provider}'; supported: {supported}"
        )

    required = PROVIDER_REQUIRED_ENV.get(provider, ())
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise ConfigError(
            f"provider '{provider}' requires env var(s) not set: {', '.join(missing)}"
        )


def _load_litellm_router_models(path: Path) -> set[str]:
    """Return the set of ``model_name`` entries in a LiteLLM router YAML.

    Tolerant: returns an empty set on missing file, empty file, or malformed
    YAML. The caller treats missing/bad router config as "no router present"
    and falls back to the ``provider/model`` form.
    """
    if not path.is_file():
        return set()
    try:
        from ruamel.yaml import YAML  # noqa: PLC0415 — ruamel is large; lazy import

        yaml = YAML(typ="safe")
        with path.open("r", encoding="utf-8") as f:
            data = yaml.load(f)
    except OSError:
        return set()
    except Exception:  # noqa: BLE001 — router yaml is advisory, never fatal
        return set()

    if not isinstance(data, dict):
        return set()
    entries = data.get("model_list") or []
    names: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("model_name")
        if isinstance(name, str):
            names.add(name)
    return names


def resolve_model_string(
    llm_config: LlmConfig,
    litellm_config_path: Path | None = None,
) -> str:
    """Return the model string to pass to ``litellm.acompletion``.

    If ``litellm_config_path`` points to a YAML with a ``model_list`` entry
    whose ``model_name`` matches ``llm_config.model``, the router resolves
    it — pass the bare name through.

    Otherwise, return ``f"{provider}/{model}"`` per LiteLLM convention. If
    the model string already starts with ``"{provider}/"`` we do not
    double-prefix.
    """
    provider = llm_config.provider
    model = llm_config.model

    router_models = (
        _load_litellm_router_models(litellm_config_path)
        if litellm_config_path is not None
        else set()
    )
    if model in router_models:
        return model

    prefix = f"{provider}/"
    if model.startswith(prefix):
        return model
    return f"{provider}/{model}"


def extra_call_params(llm_config: LlmConfig) -> dict[str, Any]:
    """Return provider-specific call kwargs to merge into ``litellm.acompletion``.

    Today this just echoes ``llm_config.params`` — LiteLLM accepts per-
    provider fields (temperature, api_base, etc.) as keyword arguments.
    """
    return dict(llm_config.params)
