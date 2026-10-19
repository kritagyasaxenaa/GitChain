from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    rocks_path: Path = Path("./data/l1")
    chain_id: str = "L1"
    chain_type: str = "L1"
    postgres_dsn: str = ""
    api_token: str | None = None
    environment: str = "development"
    p2p_enabled: bool = False
    peers: tuple[str, ...] = ()
    peer_sync_interval: float = 10.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            rocks_path=Path(os.getenv("GOC_ROCKS_PATH", "./data/l1")),
            chain_id=os.getenv("GOC_CHAIN_ID", "L1"),
            chain_type=os.getenv("GOC_CHAIN_TYPE", "L1"),
            postgres_dsn=os.getenv("GOC_POSTGRES_DSN", ""),
            api_token=os.getenv("GOC_API_TOKEN") or None,
            environment=os.getenv("GOC_ENV", "development").lower(),
            p2p_enabled=os.getenv("GOC_P2P_ENABLED", "false").strip().lower() in {"1", "true", "yes"},
            peers=tuple(peer.strip().rstrip("/") for peer in os.getenv("GOC_PEERS", "").split(",") if peer.strip()),
            peer_sync_interval=float(os.getenv("GOC_PEER_SYNC_INTERVAL", "10")),
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
        if not 1 <= self.peer_sync_interval <= 3600:
            raise ValueError("GOC_PEER_SYNC_INTERVAL must be between 1 and 3600 seconds")
        if self.peers and not self.p2p_enabled:
            raise ValueError("GOC_P2P_ENABLED must be true when GOC_PEERS is configured")
        if self.p2p_enabled and self.postgres_dsn:
            raise ValueError("PostgreSQL projection is not supported on reorganization-capable P2P nodes")
        for peer in self.peers:
            parsed = urlsplit(peer)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("GOC_PEERS entries must be base HTTP(S) URLs without credentials, query, or fragment")
            if self.environment == "production" and parsed.scheme != "https":
                raise ValueError("GOC_PEERS entries must use HTTPS when GOC_ENV=production")
