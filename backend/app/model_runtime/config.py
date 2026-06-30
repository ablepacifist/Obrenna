"""Config object for the model runtime, mirroring the persisted ModelEndpoint."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RuntimeConfig:
    provider: str = "openai_compatible"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    models: dict[str, str] = field(default_factory=dict)

    @property
    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def model_for(self, role: str, default: str = "") -> str:
        return self.models.get(role) or default

    @property
    def runtime_kind(self) -> str:
        base = (self.base_url or "").lower()
        provider = (self.provider or "").lower()
        if "11434" in base or "ollama" in base:
            return "ollama"
        if provider == "openai_compatible":
            return "openai_compatible_unknown"
        return provider or "openai_compatible_unknown"

    @property
    def supports_pull(self) -> bool:
        return self.runtime_kind == "ollama"

    @property
    def supports_streaming_progress(self) -> bool:
        return self.runtime_kind == "ollama"
