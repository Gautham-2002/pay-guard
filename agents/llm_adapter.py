"""LLM adapter setup shared by PayGuard remote Band agents."""

from __future__ import annotations

import os

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

FEATHERLESS_BASE_URL = "https://api.featherless.ai/v1"
AIML_BASE_URL = "https://api.aimlapi.com/v1"

DEFAULT_FEATHERLESS_MODEL = "meta-llama/Llama-3.3-70B-Instruct"
DEFAULT_AIML_MODEL = "gpt-4o"
DEFAULT_AIML_VERDICT_MODEL = "claude-3-5-sonnet"


def make_llm_adapter(
    *,
    provider: str,
    system_prompt: str,
    model: str | None = None,
    max_tokens: int = 4096,
    tools: list[object] | None = None,
) -> object:
    """Create a Band LangGraphAdapter using an OpenAI-compatible provider."""
    try:
        from band.adapters import LangGraphAdapter
    except ImportError as exc:
        raise RuntimeError(
            "Remote agent dependencies are missing. Run `uv sync --extra remote-agents` "
            "to install band-sdk[langgraph]."
        ) from exc

    try:
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import InMemorySaver
    except ImportError as exc:
        raise RuntimeError(
            "Remote agent dependencies are missing. Run `uv sync --extra remote-agents` "
            "to install band-sdk[langgraph]."
        ) from exc

    provider_key = provider.upper()
    if provider_key == "FEATHERLESS":
        api_key_env = "FEATHERLESS_API_KEY"
        base_url_env = "FEATHERLESS_BASE_URL"
        model_env = "FEATHERLESS_MODEL"
        default_base_url = FEATHERLESS_BASE_URL
        default_model = DEFAULT_FEATHERLESS_MODEL
    elif provider_key == "AIML":
        api_key_env = "AIML_API_KEY"
        base_url_env = "AIML_BASE_URL"
        model_env = "AIML_MODEL"
        default_base_url = AIML_BASE_URL
        default_model = DEFAULT_AIML_MODEL
    else:
        raise ValueError(f"Unsupported LLM provider: {provider!r}")

    api_key = os.getenv(api_key_env)
    if not api_key:
        raise RuntimeError(f"{api_key_env} is required before starting {provider_key} agents.")

    llm = ChatOpenAI(
        model=model or os.getenv(model_env, default_model),
        api_key=api_key,
        base_url=os.getenv(base_url_env, default_base_url),
        max_tokens=max_tokens,
    )

    return LangGraphAdapter(
        llm=llm,
        checkpointer=InMemorySaver(),
        additional_tools=tools or [],
        custom_section=system_prompt,
        enable_execution_reporting=True,
    )
