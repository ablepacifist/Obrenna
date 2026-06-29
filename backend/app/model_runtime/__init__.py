"""OpenAI-compatible local model adapter. Local-first: no cloud APIs hardcoded."""
from .client import chat_completion, list_models, test_connection
from .config import RuntimeConfig

__all__ = ["RuntimeConfig", "chat_completion", "list_models", "test_connection"]
