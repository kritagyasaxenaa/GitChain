from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from gitchain.config import Settings

logger = logging.getLogger("gitchain.api")
EngineFactory = Callable[[Settings], Any]


def _open_engine(settings: Settings) -> Any:
    try:
        import goc_core
    except ImportError as exc:
        raise RuntimeError(
            "The goc_core pybind11 extension is unavailable. Install GitChain with `pip install .` "
            "after installing its native system dependencies."
        ) from exc

    settings.rocks_path.parent.mkdir(parents=True, exist_ok=True)
    return goc_core.Engine(
        str(settings.rocks_path),
        settings.chain_id,
        settings.chain_type,
        settings.postgres_dsn,
    )


class BlockSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block: dict[str, Any]


class BlocksAfterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator: list[str] = Field(max_length=256)


def create_app(
    settings: Settings | None = None,
    engine_factory: EngineFactory = _open_engine,
) -> FastAPI:
    service_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.engine = engine_factory(service_settings)
        try:
            yield
        finally:
            del application.state.engine

    is_production = service_settings.environment == "production"
    application = FastAPI(
        title="GitChain API",
        version="0.2.0",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
        lifespan=lifespan,
    )

    def get_engine(request: Request) -> Any:
        engine = getattr(request.app.state, "engine", None)
        if engine is None:
            raise HTTPException(status_code=503, detail="Blockchain engine is not ready")
        return engine

    def authorize_write(authorization: str | None = Header(default=None)) -> None:
        expected_token = service_settings.api_token
        if expected_token is None:
            return
        expected_header = f"Bearer {expected_token}"
        if authorization is None or not hmac.compare_digest(authorization, expected_header):
            raise HTTPException(status_code=401, detail="Valid bearer token required")

    @application.get("/health/live", tags=["health"])
    def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready", tags=["health"])
    def readiness(request: Request) -> dict[str, Any]:
        engine = get_engine(request)
        try:
            status = engine.status()
        except Exception as exc:
            logger.exception("Blockchain engine readiness check failed")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc
        return {"status": "ready", "chain": status}

    @application.get("/health", tags=["health"])
    def health(request: Request) -> dict[str, Any]:
        return readiness(request)

    @application.get("/chain/status", tags=["chain"])
    def chain_status(request: Request) -> dict[str, Any]:
        try:
            return get_engine(request).status()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unable to read chain status")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc

    @application.get("/chain/locator", tags=["chain"])
    def chain_locator(
        request: Request,
        limit: int = Query(default=32, ge=1, le=256),
    ) -> dict[str, list[str]]:
        try:
            return {"locator": get_engine(request).locator(limit)}
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unable to read chain locator")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc

    @application.post("/chain/blocks-after", tags=["chain"])
    def blocks_after_common_ancestor(
        body: BlocksAfterRequest,
        request: Request,
    ) -> list[dict[str, Any]]:
        try:
            encoded_blocks = get_engine(request).blocks_after_common_ancestor_json(body.locator)
            return json.loads(encoded_blocks)
        except HTTPException:
            raise
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail="Invalid block locator") from exc
        except Exception as exc:
            logger.exception("Unable to read blocks after common ancestor")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc

    @application.get("/blocks/{block_hash}", tags=["blocks"])
    def get_block(
        request: Request,
        block_hash: str = Path(pattern=r"^[0-9a-fA-F]{64}$"),
    ) -> dict[str, Any]:
        try:
            block_json = get_engine(request).get_block_json(block_hash)
            block = json.loads(block_json)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unable to read block")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc
        if block is None:
            raise HTTPException(status_code=404, detail="Block not found")
        return block

    @application.post(
        "/blocks",
        tags=["blocks"],
        dependencies=[Depends(authorize_write)],
    )
    def submit_block(body: BlockSubmission, request: Request) -> dict[str, Any]:
        try:
            result = get_engine(request).submit_block(
                json.dumps(body.block, separators=(",", ":"), ensure_ascii=False)
            )
        except HTTPException:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail="Invalid block data") from exc
        except Exception as exc:
            logger.exception("Block submission failed inside the native engine")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc
        if not result.get("accepted", False):
            raise HTTPException(status_code=422, detail=result.get("reason") or "Block rejected")
        return result

    return application


app = create_app()