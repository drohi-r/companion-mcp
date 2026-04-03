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
    timeout_s: float = 10.0

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def _parse_timeout(env_name: str, default: str) -> float:
    raw = os.getenv(env_name, default)
    try:
        timeout_s = float(raw)
    except ValueError:
        raise ValueError(f"{env_name}={raw!r} is not a valid number") from None
    if timeout_s <= 0:
        raise ValueError(f"{env_name}={timeout_s} must be > 0")
    return timeout_s


def load_config() -> CompanionConfig:
    return CompanionConfig(
        host=os.getenv("COMPANION_HOST", "127.0.0.1"),
        port=_parse_port("COMPANION_PORT", "8000"),
        timeout_s=_parse_timeout("COMPANION_TIMEOUT_S", "10.0"),
    )
