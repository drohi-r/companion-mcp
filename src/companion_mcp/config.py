from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_port(env_name: str, default: str) -> int:
    raw = os.getenv(env_name, default)
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f"{env_name}={raw!r} is not a valid integer") from None
    if not (1 <= port <= 65535):
        raise ValueError(f"{env_name}={port} is outside valid port range 1-65535")
    return port


@dataclass(frozen=True)
class CompanionConfig:
    host: str = "127.0.0.1"
    port: int = 8000

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_config() -> CompanionConfig:
    return CompanionConfig(
        host=os.getenv("COMPANION_HOST", "127.0.0.1"),
        port=_parse_port("COMPANION_PORT", "8000"),
    )
