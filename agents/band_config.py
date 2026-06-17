"""Configuration helpers for PayGuard Band remote agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parent.parent / "agent_config.yaml"


@dataclass(frozen=True)
class RemoteAgentConfig:
    key: str
    agent_id: str
    api_key: str
    handle: str
    display_name: str
    provider: str
    model: str | None
    max_tokens: int
    next_agent_key: str | None = None
    next_handle: str | None = None


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in ("", "null", "None", "~"):
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def _normalize_handle(value: Any) -> str:
    """Return a Band handle without a leading @ for consistent mentions."""
    return str(value or "").strip().lstrip("@")


def _load_raw_config(path: Path = CONFIG_PATH) -> dict[str, dict[str, Any]]:
    """
    Load the simple agent_config.yaml shape used by Band examples.

    This avoids adding PyYAML to the base app just to read flat config blocks.
    The parser intentionally supports only the key/value structure documented in
    agent_config.example.yaml.
    """
    if not path.exists():
        raise RuntimeError(
            f"{path} is missing. Copy agent_config.example.yaml to {path} and fill it in."
        )

    config: dict[str, dict[str, Any]] = {}
    current_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            current_key = line[:-1].strip()
            config[current_key] = {}
            continue
        if current_key is None or ":" not in line:
            continue
        field, value = line.split(":", 1)
        config[current_key][field.strip()] = _parse_scalar(value)

    return config


def load_remote_agent_configs(path: Path = CONFIG_PATH) -> dict[str, RemoteAgentConfig]:
    """Load every remote agent config block."""
    raw_config = _load_raw_config(path)
    configs: dict[str, RemoteAgentConfig] = {}

    for key, values in raw_config.items():
        agent_id = str(values.get("agent_id") or "")
        api_key = str(values.get("api_key") or "")
        handle = _normalize_handle(values.get("handle"))
        if not agent_id or not api_key or not handle:
            raise RuntimeError(
                f"Agent config '{key}' must include agent_id, api_key, and handle."
            )

        max_tokens_raw = values.get("max_tokens", 4096)
        try:
            max_tokens = int(max_tokens_raw)
        except (TypeError, ValueError):
            raise RuntimeError(f"Agent config '{key}' has invalid max_tokens: {max_tokens_raw!r}")

        configs[key] = RemoteAgentConfig(
            key=key,
            agent_id=agent_id,
            api_key=api_key,
            handle=handle,
            display_name=str(values.get("display_name") or key.replace("_", " ").title()),
            provider=str(values.get("provider") or "aiml"),
            model=str(values["model"]) if values.get("model") else None,
            max_tokens=max_tokens,
            next_agent_key=(
                str(values["next_agent_key"]) if values.get("next_agent_key") else None
            ),
            next_handle=(
                _normalize_handle(values["next_handle"])
                if values.get("next_handle")
                else None
            ),
        )

    for config in configs.values():
        if config.next_agent_key and config.next_agent_key not in configs:
            raise RuntimeError(
                f"Agent config '{config.key}' references unknown next_agent_key "
                f"'{config.next_agent_key}'."
            )

    return configs


def load_remote_agent_config(key: str, path: Path = CONFIG_PATH) -> RemoteAgentConfig:
    """Load one remote agent config block."""
    configs = load_remote_agent_configs(path)
    if key not in configs:
        raise RuntimeError(f"Agent config '{key}' was not found in {path}.")
    return configs[key]


def resolve_next_handle(
    config: RemoteAgentConfig,
    all_configs: dict[str, RemoteAgentConfig],
) -> str | None:
    """Return the configured downstream Band handle for an agent."""
    if config.next_handle:
        return config.next_handle
    if config.next_agent_key:
        return all_configs[config.next_agent_key].handle
    return None
