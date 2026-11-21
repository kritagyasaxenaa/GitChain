from __future__ import annotations

import hmac
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
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

    rocks_path = Path(settings.rocks_path)
    rocks_path.parent.mkdir(parents=True, exist_ok=True)
    return goc_core.Engine(
        str(rocks_path),
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


class CreateIdentityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)


class SignTransactionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction: dict[str, Any]
    private_key_pem: str


class BuildBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_type: str = "L1"
    chain_id: str = "L1"
    height: int = Field(ge=0)
    previous_hash: str = ""
    target_hex: str = Field(min_length=64, max_length=64)
    transactions: list[dict[str, Any]] = Field(default_factory=list)
    producer_public_key: str


class MineBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block: dict[str, Any]
    private_key_pem: str
    max_attempts: int = Field(default=100000, ge=1, le=10000000)


class VerifyBlockRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block: dict[str, Any]


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
        version="0.3.0",
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
        lifespan=lifespan,
    )

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.exists():
        application.mount(
            "/static",
            StaticFiles(directory=str(static_dir)),
            name="static",
        )

        @application.get("/", response_class=HTMLResponse, include_in_schema=False)
        def serve_ui():
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(str(index_path))
            return HTMLResponse("<h1>GitChain API</h1><p>UI is ready.</p>")

        @application.get("/ui", response_class=HTMLResponse, include_in_schema=False)
        def serve_ui_alias():
            return serve_ui()

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

    @application.get("/api/chain/blocks", tags=["chain"])
    def list_chain_blocks(
        request: Request,
        limit: int = Query(default=100, ge=1, le=500),
        reverse: bool = Query(default=True),
    ) -> list[dict[str, Any]]:
        try:
            encoded_blocks = get_engine(request).blocks_after_common_ancestor_json([])
            blocks = json.loads(encoded_blocks) if encoded_blocks else []
            if reverse:
                blocks.reverse()
            return blocks[:limit]
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Unable to list blocks")
            raise HTTPException(status_code=503, detail="Blockchain engine unavailable") from exc

    @application.get("/blocks/{block_hash}", tags=["blocks"])
    def get_block(
        request: Request,
        block_hash: str = PathParam(pattern=r"^[0-9a-fA-F]{64}$"),
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

    @application.post("/api/tools/create-identity", tags=["tools"])
    def tool_create_identity(body: CreateIdentityRequest) -> dict[str, Any]:
        try:
            import goc_core
            return json.loads(goc_core.create_local_identity(body.username))
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to create identity: {exc}") from exc

    @application.post("/api/tools/generate-keypair", tags=["tools"])
    def tool_generate_keypair() -> dict[str, Any]:
        try:
            import goc_core
            return json.loads(goc_core.generate_keypair())
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Failed to generate keypair: {exc}") from exc

    @application.post("/api/tools/sign-transaction", tags=["tools"])
    def tool_sign_transaction(body: SignTransactionRequest) -> dict[str, Any]:
        try:
            import goc_core
            tx_json = json.dumps(body.transaction, separators=(",", ":"), ensure_ascii=False)
            sig = goc_core.sign_transaction(tx_json, body.private_key_pem)
            tx = dict(body.transaction)
            tx["signature_hex"] = sig
            return {"signature_hex": sig, "transaction": tx}
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Signing failed: {exc}") from exc

    @application.post("/api/tools/build-block", tags=["tools"])
    def tool_build_block(body: BuildBlockRequest) -> dict[str, Any]:
        try:
            import goc_core
            txs_json = json.dumps(body.transactions, separators=(",", ":"), ensure_ascii=False)
            block_json = goc_core.build_block(
                body.chain_type,
                body.chain_id,
                body.height,
                body.previous_hash,
                body.target_hex,
                txs_json,
                body.producer_public_key,
            )
            return {"block": json.loads(block_json)}
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Block build failed: {exc}") from exc

    @application.post("/api/tools/mine-block", tags=["tools"])
    def tool_mine_block(body: MineBlockRequest) -> dict[str, Any]:
        try:
            import goc_core
            block_json = json.dumps(body.block, separators=(",", ":"), ensure_ascii=False)
            mined_json = goc_core.mine_block(block_json, body.private_key_pem, body.max_attempts)
            mined_block = json.loads(mined_json)
            score = goc_core.score_block(
                mined_block["header"]["target_hex"],
                mined_block["hash_hex"]
            )
            return {"mined_block": mined_block, "score": score}
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Mining failed: {exc}") from exc

    @application.post("/api/tools/verify-block", tags=["tools"])
    def tool_verify_block(body: VerifyBlockRequest) -> dict[str, Any]:
        try:
            import goc_core
            block_json = json.dumps(body.block, separators=(",", ":"), ensure_ascii=False)
            return {"valid_pow": goc_core.verify_block_pow(block_json)}
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Verification failed: {exc}") from exc

    @application.post(
        "/api/chain/seed-demo",
        tags=["chain"],
        dependencies=[Depends(authorize_write)],
    )
    def seed_demo_chain(request: Request) -> dict[str, Any]:
        engine = get_engine(request)
        try:
            import goc_core
        except ImportError as exc:
            raise HTTPException(status_code=503, detail="goc_core extension unavailable") from exc

        status = engine.status()
        if status.get("tip_hash"):
            return {
                "message": "Chain is already initialized",
                "tip_height": status.get("tip_height"),
                "tip_hash": status.get("tip_hash"),
            }

        alice = json.loads(goc_core.create_local_identity("alice"))
        alice_pub = alice["keys"]["public_key_pem"]
        alice_priv = alice["keys"]["private_key_pem"]
        target = "f" * 64
        chain_id = service_settings.chain_id
        chain_type = service_settings.chain_type

        # 0: Genesis
        b0_tmpl = goc_core.build_block(chain_type, chain_id, 0, "", target, "[]", alice_pub)
        b0_mined = goc_core.mine_block(b0_tmpl, alice_priv, 1000)
        r0 = engine.submit_block(b0_mined)
        parent = r0["tip_hash"]

        # 1: User Alice
        tx1 = {
            "operation": "USER_CREATE",
            "actor_public_key": alice_pub,
            "repository_id": "",
            "payload": {"username": "alice", "identity_id": alice["identity_id"]},
            "signature_hex": "",
        }
        tx1["signature_hex"] = goc_core.sign_transaction(json.dumps(tx1, separators=(",", ":")), alice_priv)
        b1_tmpl = goc_core.build_block(chain_type, chain_id, 1, parent, target, json.dumps([tx1]), alice_pub)
        b1_mined = goc_core.mine_block(b1_tmpl, alice_priv, 1000)
        r1 = engine.submit_block(b1_mined)
        parent = r1["tip_hash"]

        # 2: Repo
        tx2 = {
            "operation": "REPO_CREATE",
            "actor_public_key": alice_pub,
            "repository_id": "gitchain-main",
            "payload": {"repository_id": "gitchain-main"},
            "signature_hex": "",
        }
        tx2["signature_hex"] = goc_core.sign_transaction(json.dumps(tx2, separators=(",", ":")), alice_priv)
        b2_tmpl = goc_core.build_block(chain_type, chain_id, 2, parent, target, json.dumps([tx2]), alice_pub)
        b2_mined = goc_core.mine_block(b2_tmpl, alice_priv, 1000)
        r2 = engine.submit_block(b2_mined)
        parent = r2["tip_hash"]

        # 3: File change
        tx3 = {
            "operation": "FILE_CHANGE",
            "actor_public_key": alice_pub,
            "repository_id": "gitchain-main",
            "payload": {"path": "README.md", "action": "create", "message": "Initial commit on GitChain"},
            "signature_hex": "",
        }
        tx3["signature_hex"] = goc_core.sign_transaction(json.dumps(tx3, separators=(",", ":")), alice_priv)
        b3_tmpl = goc_core.build_block(chain_type, chain_id, 3, parent, target, json.dumps([tx3]), alice_pub)
        b3_mined = goc_core.mine_block(b3_tmpl, alice_priv, 1000)
        r3 = engine.submit_block(b3_mined)

        return {
            "message": "Demo chain seeded successfully with 4 blocks",
            "tip_height": 3,
            "tip_hash": r3["tip_hash"],
            "alice_identity": alice,
        }

    return application


app = create_app()
