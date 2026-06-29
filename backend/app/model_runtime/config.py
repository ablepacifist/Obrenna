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
