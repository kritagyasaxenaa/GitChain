from __future__ import annotations

import asyncio
import hmac
import json
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
from typing import Any, Callable

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from gitchain.config import Settings

logger = logging.getLogger("gitchain.api")
EngineFactory = Callable[[Settings], Any]
MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_SYNC_BLOCKS = 512
MAX_SYNC_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_TRANSACTIONS_PER_BLOCK = 1000
PEER_BLOCKS_PER_MINUTE = 120
_peer_rate_lock = threading.Lock()
_peer_block_times: dict[str, deque[float]] = defaultdict(deque)


class RequestSizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        declared_length = headers.get(b"content-length")
        if declared_length is not None:
            try:
                declared_size = int(declared_length)
            except ValueError:
                await self._reject(send, 400, "Invalid Content-Length")
                return
            if declared_size < 0:
                await self._reject(send, 400, "Invalid Content-Length")
                return
            if declared_size > self.max_bytes:
                await self._reject(send, 413, "Request body is too large")
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.max_bytes:
                await self._reject(send, 413, "Request body is too large")
                return
            if not message.get("more_body", False):
                break

        body_sent = False

        async def replay_body() -> Message:
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay_body, send)

    @staticmethod
    async def _reject(send: Send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode("ascii"))],
        })
        await send({"type": "http.response.body", "body": body, "more_body": False})


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

    @field_validator("block")
    @classmethod
    def validate_transaction_count(cls, block: dict[str, Any]) -> dict[str, Any]:
        transactions = block.get("transactions")
        if not isinstance(transactions, list) or len(transactions) > MAX_TRANSACTIONS_PER_BLOCK:
            raise ValueError(f"block must contain no more than {MAX_TRANSACTIONS_PER_BLOCK} transactions")
        return block


class BlocksAfterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locator: list[str] = Field(max_length=256)
    limit: int = Field(default=MAX_SYNC_BLOCKS, ge=1, le=MAX_SYNC_BLOCKS)


def create_app(
    settings: Settings | None = None,
    engine_factory: EngineFactory = _open_engine,
) -> FastAPI:
    service_settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.engine = engine_factory(service_settings)
        sync_task = None
        if service_settings.p2p_enabled and service_settings.peers:
            sync_task = asyncio.create_task(_sync_peers(application.state.engine, service_settings))
        try:
            yield
        finally:
            if sync_task is not None:
                sync_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sync_task
            del application.state.engine

    is_production = service_settings.environment == "production"
    application = FastAPI(
        title="GitChain API",
        version="0.3.0",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
        lifespan=lifespan,
    )

    application.add_middleware(RequestSizeLimitMiddleware, max_bytes=MAX_REQUEST_BYTES)

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
            engine = get_engine(request)
            max_blocks = body.limit
            while True:
                encoded_blocks = engine.blocks_after_common_ancestor_json(body.locator, max_blocks)
                if len(encoded_blocks.encode("utf-8")) <= MAX_SYNC_RESPONSE_BYTES:
                    break
                if max_blocks == 1:
                    raise HTTPException(status_code=413, detail="A block exceeds the synchronization response limit")
                max_blocks = max(1, max_blocks // 2)
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
    def submit_block(
        body: BlockSubmission,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
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
        if service_settings.p2p_enabled and result.get("reason") != "Block already known":
            background_tasks.add_task(_relay_block, service_settings.peers, body.block)
        return result

    @application.post("/peer/blocks", tags=["peer"])
    def receive_peer_block(
        body: BlockSubmission,
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> dict[str, Any]:
        if not service_settings.p2p_enabled:
            raise HTTPException(status_code=404, detail="Peer networking is disabled")
        if not _allow_peer_block(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail="Peer block rate limit exceeded")
        try:
            result = get_engine(request).submit_block(
                json.dumps(body.block, separators=(",", ":"), ensure_ascii=False)
            )
        except HTTPException:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail="Invalid peer block data") from exc
        except Exception as exc:
            logger.exception("Peer block validation failed inside the native engine")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc
        if not result.get("accepted", False):
            raise HTTPException(status_code=422, detail=result.get("reason") or "Block rejected")
        if result.get("reason") != "Block already known":
            background_tasks.add_task(_relay_block, service_settings.peers, body.block)
        return result

    return application


async def _sync_peers(engine: Any, settings: Settings) -> None:
    timeout = httpx.Timeout(20.0, connect=4.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            for peer in settings.peers:
                try:
                    content = bytearray()
                    async with client.stream(
                        "POST",
                        f"{peer}/chain/blocks-after",
                        json={"locator": engine.locator(32), "limit": MAX_SYNC_BLOCKS},
                    ) as response:
                        response.raise_for_status()
                        async for chunk in response.aiter_bytes():
                            if len(content) + len(chunk) > MAX_SYNC_RESPONSE_BYTES:
                                raise ValueError("peer synchronization response exceeded the size limit")
                            content.extend(chunk)
                    blocks = json.loads(content)
                    if not isinstance(blocks, list) or len(blocks) > MAX_SYNC_BLOCKS:
                        logger.warning("Peer %s returned an invalid or oversized block batch", peer)
                        continue
                    for block in blocks:
                        result = engine.submit_block(
                            json.dumps(block, separators=(",", ":"), ensure_ascii=False)
                        )
                        if not result.get("accepted", False):
                            logger.warning("Peer %s supplied a rejected block: %s", peer, result.get("reason"))
                            break
                except (httpx.HTTPError, ValueError, TypeError, RuntimeError, KeyError) as exc:
                    logger.warning("Unable to synchronize from peer %s: %s", peer, exc)
            await asyncio.sleep(settings.peer_sync_interval)


def _relay_block(peers: tuple[str, ...], block: dict[str, Any]) -> None:
    if not peers:
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
            for peer in peers:
                try:
                    response = client.post(f"{peer}/peer/blocks", json={"block": block})
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    logger.warning("Unable to relay block to peer %s: %s", peer, exc)
    except httpx.HTTPError as exc:
        logger.warning("Unable to initialize peer relay: %s", exc)


def _allow_peer_block(remote_address: str) -> bool:
    now = time.monotonic()
    cutoff = now - 60
    with _peer_rate_lock:
        requests = _peer_block_times[remote_address]
        while requests and requests[0] < cutoff:
            requests.popleft()
        if len(requests) >= PEER_BLOCKS_PER_MINUTE:
            return False
        requests.append(now)
        if len(_peer_block_times) > 10_000:
            for address, samples in list(_peer_block_times.items()):
                if not samples or samples[-1] < cutoff:
                    _peer_block_times.pop(address, None)
        return True


app = create_app()
