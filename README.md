# GitChain

GitChain is an undeployed local-chain application with a C++20 engine, pybind11 module, command-line interface, and FastAPI service. It stores one sequential chain in RocksDB. Use a distinct chain ID and database directory for each chain.

## Simple chain

For each valid block, with 256-bit target `T` and block hash integer `h`:

`block_score = floor(sqrt(T - h))`

`chain_score = sum(block_score)`

The code uses exact integer arithmetic (`boost::multiprecision::cpp_int`) and an integer square root. The genesis block selects the target; every later block must keep it unchanged. Blocks must extend the current tip, and side branches are rejected. The score is reported for the linear chain and is not used to switch branches.

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

This is a local, single-chain implementation without peer networking. Consensus replays canonical transactions from RocksDB and enforces registration, repository ownership, role grants, and file-change permissions. PostgreSQL is an optional libpqxx projection, not consensus authority.

## File map

- `src/CreateBlock.cpp` — block construction, mining, encoding
- `src/Crypto.cpp` — SHA-256, ECDSA P-256, integer parsing, integer square root, score
- `src/Block.cpp` — L1/L2 block and transaction serialization
- `src/PostGres.cpp` — canonical projection and basic reads
- `src/Consensus.cpp` — validation, RocksDB storage, score accumulation, locators
- `src/AccessControl.cpp` — access request/grant/revoke transaction construction
- `src/UserReg.cpp` — local key generation and registration transaction construction

## CLI and FastAPI

The CLI reads `GOC_ROCKS_PATH` (default `./data/l1`), `GOC_CHAIN_ID` (default `L1`), `GOC_CHAIN_TYPE` (`L1` or `L2`), optional `GOC_POSTGRES_DSN`, `GOC_ENV`, and `GOC_API_TOKEN` from the environment.

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

HTTP endpoints include `GET /health/live`, `GET /health/ready`, `GET /chain/status`, `GET /chain/locator`, `POST /chain/blocks-after`, `GET /blocks/{hash}`, and authenticated `POST /blocks`. In development, interactive docs are available at `/docs`.

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

**Deployment status:** not deployed. This version is a single-node local chain with a fixed genesis target and stateful role checks. It has no peer networking and has not had an independent security audit; keep it on localhost until a network protocol and deployment model are defined and reviewed.
