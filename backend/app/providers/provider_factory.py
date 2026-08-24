import os

from ..config import AI_PROVIDER_ENV, DEFAULT_AI_PROVIDER
from .ollama_provider import OllamaProvider

SUPPORTED_PROVIDERS = {"claude", "ollama", "nvidia"}


def get_ai_provider():
    provider_name = os.getenv(AI_PROVIDER_ENV, DEFAULT_AI_PROVIDER).strip().lower()

    if provider_name == "claude":
        from .claude_provider import ClaudeProvider

        return ClaudeProvider()
    if provider_name == "ollama":
        return OllamaProvider()
    if provider_name == "nvidia":
        from .nvidia_provider import NvidiaProvider

        return NvidiaProvider()

    raise RuntimeError(
        f"Unsupported AI_PROVIDER '{provider_name}'. Supported values: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
    )
