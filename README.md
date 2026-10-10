# GitChain

GitChain is a C++20 chain engine exposed to Python through pybind11, with a FastAPI service and a command-line interface. It is an experimental prototype, not production-ready blockchain software. L1 and L2 must use distinct chain IDs and RocksDB directories.

## Fork-choice score

For each valid block, with 256-bit target `T` and block hash integer `h`:

`block_score = floor(sqrt(T - h))`

`chain_score = sum(block_score)`

The code uses exact integer arithmetic (`boost::multiprecision::cpp_int`) and an integer square root. A node chooses the valid branch with the greatest accumulated score. Equal scores retain the current branch. This is a custom rule, not standard accumulated proof-of-work.

## Install

The pybind11 extension is built with setuptools; CMake is not used. Install native development packages first.

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

## Important limitations to resolve before connecting untrusted peers

1. **Networking is not implemented.** `CreateBlock::encode`, locators, and block-serving helpers provide a boundary for a P2P transport layer; they do not broadcast or open peer connections themselves.
2. **Reorganizations are not implemented end-to-end.** Competing blocks are retained, but the canonical index and PostgreSQL projection are only advanced for direct tip extensions. The code intentionally refuses to silently reorganize PostgreSQL state. Implement branch switching plus undo/replay before treating competing-branch handling as complete.
3. **Transaction authorization is incomplete.** Signatures are checked, but operation-specific role/permission validation against the parent chain state is not implemented. PostgreSQL must not be the authority for consensus validation.
4. **Transaction signing convention:** sign `transactionToJson(tx)` after clearing `signature_hex`; use `Crypto::signTransaction` to create that signature. The block producer signs the final block hash after mining.
5. **Target policy is incomplete.** This prototype accepts the target in each block. A real protocol must define how target values are selected and validated; otherwise peers can submit easy targets.
6. **Identity persistence is incomplete.** The CLI writes plaintext private keys to owner-only files; use secure key storage for real secrets. Username uniqueness and registration policy need consensus validation.
7. **PostgreSQL rollback is deliberately not implemented.** `rollbackBlock` throws after updating projection metadata because reversing application state safely requires undo data. Do not enable automatic reorgs until this is replaced.
8. **Consensus hashing format is protocol-critical.** Header serialization uses ordered JSON fields. Once nodes are deployed, never change serialization without a protocol/version change.
9. **Hash serialization is protocol-critical.** This scaffold hashes the canonical header, transaction array, and producer public key. A production implementation should add protocol versioning and test vectors before nodes are deployed.

## File map

- `src/CreateBlock.cpp` — block construction, mining, encoding
- `src/Crypto.cpp` — SHA-256, ECDSA P-256, integer parsing, integer square root, score
- `src/Block.cpp` — L1/L2 block and transaction serialization
- `src/PostGres.cpp` — canonical projection and basic reads
- `src/Consensus.cpp` — validation, RocksDB storage, score accumulation, locators
- `src/AccessControl.cpp` — access request/grant/revoke transaction construction
- `src/UserReg.cpp` — local key generation and registration transaction construction

This scaffold is intended to be reviewed and completed module by module. Do not run it on a public network or treat it as secure yet.

## CLI and FastAPI

The CLI reads `GOC_ROCKS_PATH` (default `./data/l1`), `GOC_CHAIN_ID` (default `L1`), `GOC_CHAIN_TYPE` (`L1` or `L2`), optional `GOC_POSTGRES_DSN`, `GOC_ENV`, and `GOC_API_TOKEN` from the environment.

```bash
gitchain create-identity alice --output "$HOME/.config/gitchain/alice.json"
gitchain status
gitchain serve --host 127.0.0.1 --port 8000
```

Block production commands are also available: `sign-transaction`, `build-block`, `mine-block`, and `submit-block`. Run `gitchain --help` for options.

Identity and keypair commands create their output file exclusively with owner-only permissions and do not print private keys. The key file is still plaintext; protect it and use secure key storage for real secrets.

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

**Security warning:** this is a development prototype. Do not expose it to untrusted peers or use it to protect valuable assets. Operation-specific authorization, target-policy validation, canonical-chain reorganization with PostgreSQL rollback/replay, peer networking, and secure persistent key management are incomplete. These consensus and state-management gaps must be resolved and independently reviewed before the blockchain can be considered production-ready.
