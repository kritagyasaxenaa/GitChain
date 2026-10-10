from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    rocks_path: Path = Path("./data/l1")
    chain_id: str = "L1"
    chain_type: str = "L1"
    postgres_dsn: str = ""
    api_token: str | None = None
    environment: str = "development"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            rocks_path=Path(os.getenv("GOC_ROCKS_PATH", "./data/l1")),
            chain_id=os.getenv("GOC_CHAIN_ID", "L1"),
            chain_type=os.getenv("GOC_CHAIN_TYPE", "L1"),
            postgres_dsn=os.getenv("GOC_POSTGRES_DSN", ""),
            api_token=os.getenv("GOC_API_TOKEN") or None,
            environment=os.getenv("GOC_ENV", "development").lower(),
        )

    def __post_init__(self) -> None:
        if not self.chain_id.strip():
            raise ValueError("GOC_CHAIN_ID must not be empty")
        if self.chain_type not in {"L1", "L2"}:
            raise ValueError("GOC_CHAIN_TYPE must be 'L1' or 'L2'")
        if self.environment not in {"development", "production", "test"}:
            raise ValueError("GOC_ENV must be development, production, or test")
        if self.environment == "production" and not self.api_token:
            raise ValueError("GOC_API_TOKEN is required when GOC_ENV=production")