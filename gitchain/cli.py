from __future__ import annotations

import argparse
import base64
import getpass
import hmac
import ipaddress
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from gitchain.api import _open_engine, create_app
from gitchain.config import Settings

MAX_JSON_FILE_BYTES = 5 * 1024 * 1024
IDENTITY_FORMAT = "gitchain-encrypted-identity"
IDENTITY_AAD = b"gitchain-identity-v1"


def _valid_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _read_json(path: Path) -> Any:
    size = path.stat().st_size
    if size > MAX_JSON_FILE_BYTES:
        raise ValueError(f"JSON file exceeds the {MAX_JSON_FILE_BYTES}-byte limit")
    with path.open("r", encoding="utf-8") as source:
        return json.load(source)


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


def _write_secret(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        destination.write(content)
        destination.write("\n")


def _prompt_new_passphrase() -> str:
    passphrase = getpass.getpass("New identity passphrase: ")
    confirmation = getpass.getpass("Confirm passphrase: ")
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    if not hmac.compare_digest(passphrase.encode("utf-8"), confirmation.encode("utf-8")):
        raise ValueError("passphrases do not match")
    return passphrase


def _identity_keys(identity: Any) -> dict[str, str]:
    if not isinstance(identity, dict):
        raise ValueError("identity file must contain a JSON object")
    keys = identity.get("keys", identity)
    if not isinstance(keys, dict):
        raise ValueError("identity file must contain public and private keys")
    private_key = keys.get("private_key_pem")
    public_key = keys.get("public_key_pem")
    if not isinstance(private_key, str) or not isinstance(public_key, str):
        raise ValueError("identity file must contain public_key_pem and private_key_pem")
    return {"private_key_pem": private_key, "public_key_pem": public_key}


def _encrypt_identity(identity: dict[str, Any], passphrase: str) -> str:
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode("utf-8"))
    ciphertext = AESGCM(key).encrypt(
        nonce,
        json.dumps(identity, separators=(",", ":")).encode("utf-8"),
        IDENTITY_AAD,
    )
    return json.dumps(
        {
            "format": IDENTITY_FORMAT,
            "version": 1,
            "kdf": "scrypt",
            "salt": base64.b64encode(salt).decode("ascii"),
            "cipher": "aes-256-gcm",
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        },
        indent=2,
    )


def _decrypt_identity(envelope: dict[str, Any], passphrase: str) -> dict[str, Any]:
    if (
        envelope.get("format") != IDENTITY_FORMAT
        or envelope.get("version") != 1
        or envelope.get("kdf") != "scrypt"
        or envelope.get("cipher") != "aes-256-gcm"
    ):
        raise ValueError("unsupported identity file format")
    if not passphrase:
        raise ValueError("passphrase must not be empty")
    try:
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
        key = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1).derive(passphrase.encode("utf-8"))
        identity = json.loads(AESGCM(key).decrypt(nonce, ciphertext, IDENTITY_AAD))
    except (InvalidTag, KeyError, TypeError, ValueError) as exc:
        raise ValueError("incorrect passphrase or invalid encrypted identity file") from exc
    if not isinstance(identity, dict):
        raise ValueError("decrypted identity is not a JSON object")
    return identity


def _write_output(path: Path, content: str) -> None:
    if str(path) == "-":
        print(content)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(descriptor, "w", encoding="utf-8") as destination:
        destination.write(content)
        destination.write("\n")


def _load_identity(path: Path) -> dict[str, str]:
    file_stat = path.stat()
    if os.name != "nt" and stat.S_IMODE(file_stat.st_mode) & 0o077:
        raise PermissionError(f"identity file permissions are too broad; run chmod 600 {path}")
    identity = _read_json(path)
    if not isinstance(identity, dict) or identity.get("format") != IDENTITY_FORMAT:
        raise ValueError("identity file is plaintext; encrypt it with `gitchain protect-identity`")
    decrypted = _decrypt_identity(identity, getpass.getpass("Identity passphrase: "))
    return _identity_keys(decrypted)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="gitchain", description="GitChain node and API tools")
    parser.add_argument("--version", action="version", version="gitchain 0.3.0")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the FastAPI service")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=_valid_port, default=8000)
    serve.add_argument("--log-level", choices=("critical", "error", "warning", "info", "debug"), default="info")

    commands.add_parser("status", help="show the local chain tip")
    locator = commands.add_parser("locator", help="print a chain synchronization locator")
    locator.add_argument("--limit", type=int, default=32)

    block = commands.add_parser("get-block", help="print a stored block by hash")
    block.add_argument("hash")

    blocks_after = commands.add_parser("blocks-after", help="print canonical blocks after a common ancestor")
    blocks_after.add_argument("locator", nargs="*", help="known block hashes, newest first")

    submit = commands.add_parser("submit-block", help="validate and submit a block JSON file")
    submit.add_argument("file", type=Path)

    sign = commands.add_parser("sign-transaction", help="sign a transaction JSON file")
    sign.add_argument("file", type=Path)
    sign.add_argument("--identity", required=True, type=Path)
    sign.add_argument("--output", type=Path, default=Path("-"))

    build = commands.add_parser("build-block", help="construct an unsigned block template")
    build.add_argument("--height", required=True, type=int)
    build.add_argument("--previous-hash", default="")
    build.add_argument("--target", required=True)
    build.add_argument("--transactions", required=True, type=Path)
    build.add_argument("--identity", required=True, type=Path)
    build.add_argument("--output", type=Path, default=Path("-"))

    mine = commands.add_parser("mine-block", help="mine a block template and sign its final hash")
    mine.add_argument("file", type=Path)
    mine.add_argument("--identity", required=True, type=Path)
    mine.add_argument("--output", type=Path, default=Path("-"))
    mine.add_argument("--max-attempts", type=int, default=1_000_000)

    verify = commands.add_parser("verify-block", help="verify a block's hash and proof of work")
    verify.add_argument("file", type=Path)

    identity = commands.add_parser("create-identity", help="create a local identity and write its key securely")
    identity.add_argument("username")
    identity.add_argument("--output", required=True, type=Path)

    keypair = commands.add_parser("generate-keypair", help="generate a keypair and write it securely")
    keypair.add_argument("--output", required=True, type=Path)

    protect = commands.add_parser("protect-identity", help="encrypt an existing plaintext identity file")
    protect.add_argument("file", type=Path)
    protect.add_argument("--output", required=True, type=Path)

    score = commands.add_parser("score-block", help="calculate the custom score for a target and block hash")
    score.add_argument("target_hex")
    score.add_argument("hash_hex")
    return parser


def _run(args: argparse.Namespace) -> int:
    if args.command == "serve":
        settings = Settings.from_env()
        if not _is_loopback(args.host) and not settings.api_token:
            raise ValueError("GOC_API_TOKEN is required when binding to a non-loopback address")
        import uvicorn

        uvicorn.run(
            create_app(settings),
            host=args.host,
            port=args.port,
            log_level=args.log_level,
            access_log=True,
        )
        return 0

    if args.command == "create-identity":
        import goc_core

        identity = json.loads(goc_core.create_local_identity(args.username))
        _write_secret(args.output, _encrypt_identity(identity, _prompt_new_passphrase()))
        print(f"identity_id: {identity['identity_id']}")
        print(f"key_file: {args.output}")
        return 0

    if args.command == "generate-keypair":
        import goc_core

        keys = json.loads(goc_core.generate_keypair())
        _write_secret(args.output, _encrypt_identity(keys, _prompt_new_passphrase()))
        print(f"key_file: {args.output}")
        return 0

    if args.command == "protect-identity":
        identity = _read_json(args.file)
        _identity_keys(identity)
        _write_secret(args.output, _encrypt_identity(identity, _prompt_new_passphrase()))
        print(f"encrypted_key_file: {args.output}")
        return 0

    if args.command == "sign-transaction":
        import goc_core

        transaction = _read_json(args.file)
        if not isinstance(transaction, dict):
            raise ValueError("transaction JSON must be an object")
        identity = _load_identity(args.identity)
        signature = goc_core.sign_transaction(
            json.dumps(transaction, separators=(",", ":"), ensure_ascii=False),
            identity["private_key_pem"],
        )
        transaction["signature_hex"] = signature
        _write_output(args.output, json.dumps(transaction, indent=2))
        return 0

    if args.command == "build-block":
        import goc_core

        if args.height < 0:
            raise ValueError("--height must not be negative")
        transactions = _read_json(args.transactions)
        if not isinstance(transactions, list):
            raise ValueError("transactions file must contain a JSON array")
        identity = _load_identity(args.identity)
        settings = Settings.from_env()
        block = goc_core.build_block(
            settings.chain_type,
            settings.chain_id,
            args.height,
            args.previous_hash,
            args.target,
            json.dumps(transactions, separators=(",", ":"), ensure_ascii=False),
            identity["public_key_pem"],
        )
        _write_output(args.output, json.dumps(json.loads(block), indent=2))
        return 0

    if args.command == "mine-block":
        import goc_core

        if args.max_attempts < 1:
            raise ValueError("--max-attempts must be positive")
        block = json.dumps(_read_json(args.file), separators=(",", ":"), ensure_ascii=False)
        identity = _load_identity(args.identity)
        mined_block = goc_core.mine_block(block, identity["private_key_pem"], args.max_attempts)
        _write_output(args.output, json.dumps(json.loads(mined_block), indent=2))
        return 0

    if args.command in {"verify-block", "score-block"}:
        import goc_core

        if args.command == "verify-block":
            block_json = json.dumps(_read_json(args.file), separators=(",", ":"))
            _print_json({"valid_pow": goc_core.verify_block_pow(block_json)})
        else:
            print(goc_core.score_block(args.target_hex, args.hash_hex))
        return 0

    engine = _open_engine(Settings.from_env())
    if args.command == "status":
        _print_json(engine.status())
    elif args.command == "locator":
        if not 1 <= args.limit <= 256:
            raise ValueError("--limit must be between 1 and 256")
        _print_json({"locator": engine.locator(args.limit)})
    elif args.command == "get-block":
        value = json.loads(engine.get_block_json(args.hash))
        if value is None:
            raise LookupError("Block not found")
        _print_json(value)
    elif args.command == "blocks-after":
        if len(args.locator) > 256:
            raise ValueError("at most 256 locator hashes are allowed")
        _print_json(json.loads(engine.blocks_after_common_ancestor_json(args.locator)))
    elif args.command == "submit-block":
        block_json = json.dumps(_read_json(args.file), separators=(",", ":"), ensure_ascii=False)
        result = engine.submit_block(block_json)
        _print_json(result)
        return 0 if result.get("accepted", False) else 2
    else:
        raise ValueError(f"unsupported command: {args.command}")
    return 0


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        exit_code = _run(args)
    except Exception as exc:
        parser.exit(1, f"gitchain: error: {exc}\n")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()