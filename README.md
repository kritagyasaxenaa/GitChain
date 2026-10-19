# GitChain

GitChain is an experimental blockchain node with a C++20 engine, pybind11 module, command-line interface, FastAPI service, and optional HTTP peer synchronization. It stores each node's chain data in RocksDB. Use a distinct database directory per node and the same chain ID and genesis block across nodes in one testnet.

## Simple chain

For each valid block, with 256-bit target `T` and block hash integer `h`:

`block_score = floor(sqrt(T - h))`

`chain_score = sum(block_score)`

The code uses exact integer arithmetic (`boost::multiprecision::cpp_int`) and an integer square root. The genesis block selects the target; every later block must keep it unchanged. Valid competing branches are retained, and the branch with the greater accumulated score becomes canonical. Equal scores use the lexicographically smaller tip hash as a deterministic tie-breaker. State is replayed from the branch's genesis before a candidate can be accepted.

## Install

The pybind11 extension is built with setuptools. Install native development packages first.

Fedora:

```bash
sudo dnf install gcc-c++ python3-devel pkgconf-pkg-config openssl-devel boost-devel nlohmann-json-devel rocksdb-devel libpqxx-devel
```

Debian or Ubuntu:

```bash
sudo apt install build-essential python3-dev pkg-config libssl-dev libboost-dev nlohmann-json3-dev librocksdb-dev libpqxx-dev
```

Then install the project from its root:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
```

This builds and installs `goc_core` and the `gitchain` command. `python -m pip install -r requirements-api.txt` installs the project from a checkout as well.

Version 0.3 introduces stricter target and transaction rules. Use a fresh RocksDB directory if an older local chain fails state validation during startup; no automatic migration is provided.

Consensus replays canonical transactions from RocksDB and enforces registration, repository ownership, role grants, and file-change permissions. PostgreSQL is an optional libpqxx projection, not consensus authority. The experimental HTTP peer mode described below adds block synchronization between independently operated nodes.

## File map

- `src/CreateBlock.cpp` — block construction, mining, encoding
- `src/Crypto.cpp` — SHA-256, ECDSA P-256, integer parsing, integer square root, score
- `src/Block.cpp` — L1/L2 block and transaction serialization
- `src/PostGres.cpp` — canonical projection and basic reads
- `src/Consensus.cpp` — validation, RocksDB storage, score accumulation, locators
- `src/AccessControl.cpp` — access request/grant/revoke transaction construction
- `src/UserReg.cpp` — local key generation and registration transaction construction

## CLI and FastAPI

The CLI reads `GOC_ROCKS_PATH` (default `./data/l1`), `GOC_CHAIN_ID` (default `L1`), `GOC_CHAIN_TYPE` (`L1` or `L2`), optional `GOC_POSTGRES_DSN`, `GOC_ENV`, `GOC_API_TOKEN`, `GOC_P2P_ENABLED`, `GOC_PEERS`, and `GOC_PEER_SYNC_INTERVAL` from the environment.

```bash
gitchain create-identity alice --output "$HOME/.config/gitchain/alice.json"
gitchain status
gitchain serve --host 127.0.0.1 --port 8000
```

Block production commands are also available: `sign-transaction`, `build-block`, `mine-block`, and `submit-block`. Run `gitchain --help` for options.

Identity and keypair commands prompt for a passphrase and write an encrypted file with owner-only permissions. Existing plaintext identity files can be migrated with `gitchain protect-identity old.json --output protected.json`.

To bind beyond localhost, configure a strong API token. Production mode requires the token and disables interactive API documentation:

```bash
export GOC_ENV=production
export GOC_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
gitchain serve --host 0.0.0.0 --port 8000
```

Run one server process per RocksDB directory. For network access, use a trusted reverse proxy for TLS and access controls. The `python/fastapi_example.py` module is available for ASGI deployments; the CLI is the simple default.

HTTP endpoints include `GET /health/live`, `GET /health/ready`, `GET /chain/status`, `GET /chain/locator`, `POST /chain/blocks-after`, `GET /blocks/{hash}`, and authenticated `POST /blocks`. When `GOC_P2P_ENABLED=true`, nodes also accept validated peer blocks at `POST /peer/blocks` and periodically pull canonical blocks from the comma-separated seed URLs in `GOC_PEERS`. Peer sync is static and HTTP-based; there is no automatic peer discovery. In development, interactive docs are available at `/docs`.

### Experimental multi-node testnet

This mode is for a disposable testnet, not a production mainnet. All nodes in the same network must use the same `GOC_CHAIN_ID`, `GOC_CHAIN_TYPE`, and genesis block. Start one seed node, initialize its genesis block, then configure other nodes with the seed's HTTPS API URL in `GOC_PEERS`. Nodes relay newly received blocks to configured peers and periodically request missing canonical blocks. The peer block endpoint is public when P2P is enabled; blocks still undergo hash, proof-of-work, producer-signature, transaction-signature, and state validation.

Peer nodes must use separate persistent RocksDB volumes. Do not set `GOC_POSTGRES_DSN` on P2P nodes; the optional SQL projection does not yet rebuild after a chain reorganization. `GOC_API_TOKEN` remains required in production and protects the operator's `POST /blocks` endpoint. P2P block relay uses `POST /peer/blocks` and does not share that operator token.

The repository includes a Dockerfile for Railway or another Docker host. On Railway, create one service per node, attach a separate persistent volume mounted at `/data`, and set `GOC_ROCKS_PATH=/data/l1`. Use `GOC_ENV=production`, a unique strong `GOC_API_TOKEN` per node, `GOC_P2P_ENABLED=true`, the same chain ID/type on every node, and HTTPS peer URLs. Create the first seed node without peers, initialize its genesis, then point additional nodes at it. Railway volumes support persistent data but cannot be shared among replicas, so run one replica per node. See [Railway TCP Proxy](https://docs.railway.com/networking/tcp-proxy) and [Railway Volumes](https://docs.railway.com/volumes/reference).

`benchmarks/read_api.js` measures read-route latency under a steady load. Run it against a deployed staging node with `BASE_URL`, `VUS`, and `DURATION` set; k6 reports p95 and p99. Benchmark block writes separately using unique, valid blocks on a disposable chain.

### Exposed Python API

- `goc_core.generate_keypair()`
- `goc_core.create_local_identity(username)`
- `goc_core.identity_id(public_key_pem)`
- `goc_core.sha256(data)`
- `goc_core.sign_message(private_key_pem, message)` / `verify_signature(...)`
- `goc_core.sign_transaction(transaction_json, private_key_pem)`
- `goc_core.score_block(target_hex, hash_hex)`
- `goc_core.verify_block_pow(block_json)`
- `goc_core.build_block(...)` / `mine_block(...)`
- `goc_core.access_request(...)`, `access_grant(...)`, `access_revoke(...)`
- `goc_core.Engine(...).submit_block(...)`, `.status()`, `.tip_hash()`, `.tip_height()`, `.locator()`, `.get_block_json(...)`, `.blocks_after_common_ancestor_json(...)`

**Deployment status:** not deployed. The HTTP peer sync is an early testnet implementation with static seed URLs and the current fixed-target score rule. It has not had an independent security audit, does not include automatic peer discovery or finality, and should not be used for valuable assets or production repositories.
