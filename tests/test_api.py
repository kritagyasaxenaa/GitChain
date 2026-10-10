from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from gitchain.api import create_app
from gitchain.cli import (
    _decrypt_identity,
    _encrypt_identity,
    _is_loopback,
    _load_identity,
    _prompt_new_passphrase,
    _write_secret,
)
from gitchain.config import Settings

try:
    import goc_core
except ImportError:
    goc_core = None


class FakeEngine:
    def status(self):
        return {"chain_id": "test-chain", "tip_height": 2, "tip_hash": "a" * 64}

    def locator(self, limit):
        return ["a" * 64][:limit]

    def get_block_json(self, block_hash):
        if block_hash == "a" * 64:
            return json.dumps({"hash_hex": block_hash})
        return "null"

    def blocks_after_common_ancestor_json(self, locator):
        return json.dumps([{"hash_hex": "b" * 64}])

    def submit_block(self, block_json):
        block = json.loads(block_json)
        return {
            "accepted": block.get("valid", False),
            "reason": "invalid block" if not block.get("valid", False) else "",
            "tip_height": 3,
        }


class ApiTests(unittest.TestCase):
    def setUp(self):
        settings = Settings(environment="test", api_token="test-token")
        self.client_context = TestClient(
            create_app(settings, engine_factory=lambda _: FakeEngine())
        )
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)

    def test_health_chain_and_sync_routes(self):
        self.assertEqual(self.client.get("/health/live").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/health/ready").status_code, 200)
        self.assertEqual(self.client.get("/chain/status").json()["chain_id"], "test-chain")
        self.assertEqual(self.client.get("/chain/locator").json()["locator"], ["a" * 64])
        blocks = self.client.post("/chain/blocks-after", json={"locator": ["a" * 64]})
        self.assertEqual(blocks.json(), [{"hash_hex": "b" * 64}])

    def test_block_read_and_write_auth(self):
        found = self.client.get(f"/blocks/{'a' * 64}")
        missing = self.client.get(f"/blocks/{'c' * 64}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.client.post("/blocks", json={"block": {"valid": True}}).status_code, 401)
        accepted = self.client.post(
            "/blocks",
            json={"block": {"valid": True}},
            headers={"Authorization": "Bearer test-token"},
        )
        rejected = self.client.post(
            "/blocks",
            json={"block": {"valid": False}},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 422)

    def test_input_validation(self):
        self.assertEqual(self.client.get("/chain/locator?limit=257").status_code, 422)
        self.assertEqual(self.client.get("/blocks/not-a-hash").status_code, 422)
        self.assertEqual(self.client.post("/chain/blocks-after", json={"locator": ["x"] * 257}).status_code, 422)


class CliTests(unittest.TestCase):
    def test_external_bind_addresses_are_not_loopback(self):
        self.assertTrue(_is_loopback("127.0.0.1"))
        self.assertTrue(_is_loopback("::1"))
        self.assertTrue(_is_loopback("localhost"))
        self.assertFalse(_is_loopback("0.0.0.0"))
        self.assertFalse(_is_loopback("192.0.2.1"))

    def test_secret_file_is_private_and_never_overwritten(self):
        import stat
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identity.json"
            _write_secret(path, "secret")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):
                _write_secret(path, "replacement")

    def test_identity_encryption_and_plaintext_migration_guard(self):
        import json
        import stat
        import tempfile
        from pathlib import Path

        identity = {
            "username": "alice",
            "keys": {
                "public_key_pem": "public-key",
                "private_key_pem": "private-key",
            },
        }
        encrypted = _encrypt_identity(identity, "correct horse battery staple")
        self.assertNotIn("private-key", encrypted)
        envelope = json.loads(encrypted)
        self.assertEqual(_decrypt_identity(envelope, "correct horse battery staple"), identity)
        with self.assertRaisesRegex(ValueError, "incorrect passphrase"):
            _decrypt_identity(envelope, "wrong passphrase")
        with tempfile.TemporaryDirectory() as directory:
            encrypted_path = Path(directory) / "identity.json"
            _write_secret(encrypted_path, encrypted)
            with patch("gitchain.cli.getpass.getpass", return_value="correct horse battery staple"):
                self.assertEqual(_load_identity(encrypted_path), identity["keys"])
        with patch("gitchain.cli.getpass.getpass", side_effect=["påssphrase", "påssphrase"]):
            self.assertEqual(_prompt_new_passphrase(), "påssphrase")

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            _write_secret(path, json.dumps(identity))
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(ValueError, "protect-identity"):
                _load_identity(path)


@unittest.skipIf(goc_core is None, "build the goc_core extension to run native consensus tests")
class NativeConsensusTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.temporary_directory = tempfile.TemporaryDirectory()
        self.chain_path = str(Path(self.temporary_directory.name) / "chain")
        self.target = "f" * 64
        self.engine = goc_core.Engine(self.chain_path, "authorization-test", "L1", "")

    def tearDown(self):
        import gc

        self.engine = None
        gc.collect()
        self.temporary_directory.cleanup()

    @staticmethod
    def new_keys():
        return json.loads(goc_core.generate_keypair())

    @staticmethod
    def signed_transaction(operation, keys, repository_id="", payload=None):
        transaction = {
            "operation": operation,
            "actor_public_key": keys["public_key_pem"],
            "repository_id": repository_id,
            "payload": payload or {},
            "signature_hex": "",
        }
        transaction["signature_hex"] = goc_core.sign_transaction(
            json.dumps(transaction), keys["private_key_pem"]
        )
        return transaction

    def mine_and_submit(self, height, parent_hash, transactions=(), producer_keys=None, target=None):
        producer = producer_keys or self.alice
        block_template = goc_core.build_block(
            "L1",
            "authorization-test",
            height,
            parent_hash,
            target or self.target,
            json.dumps(list(transactions)),
            producer["public_key_pem"],
        )
        block_json = goc_core.mine_block(block_template, producer["private_key_pem"], 1000)
        return json.loads(block_json), self.engine.submit_block(block_json)

    def test_roles_target_and_state_recovery(self):
        self.alice = self.new_keys()
        bob = self.new_keys()

        genesis, result = self.mine_and_submit(0, "")
        self.assertTrue(result["accepted"])
        parent_hash = genesis["hash_hex"]

        registration = self.signed_transaction(
            "USER_CREATE",
            self.alice,
            payload={
                "username": "alice",
                "identity_id": goc_core.identity_id(self.alice["public_key_pem"]),
            },
        )
        block, result = self.mine_and_submit(1, parent_hash, [registration])
        self.assertTrue(result["accepted"])
        parent_hash = block["hash_hex"]

        repository = self.signed_transaction(
            "REPO_CREATE", self.alice, "repo-1", {"repository_id": "repo-1"}
        )
        block, result = self.mine_and_submit(2, parent_hash, [repository])
        self.assertTrue(result["accepted"])
        parent_hash = block["hash_hex"]

        bob_registration = self.signed_transaction(
            "USER_CREATE",
            bob,
            payload={"username": "bob", "identity_id": goc_core.identity_id(bob["public_key_pem"])},
        )
        block, result = self.mine_and_submit(3, parent_hash, [bob_registration], bob)
        self.assertTrue(result["accepted"])
        parent_hash = block["hash_hex"]

        unauthorized_change = self.signed_transaction("FILE_CHANGE", bob, "repo-1", {"path": "README.md"})
        block, result = self.mine_and_submit(4, parent_hash, [unauthorized_change], bob)
        self.assertFalse(result["accepted"])

        grant = self.signed_transaction(
            "ACCESS_GRANT",
            self.alice,
            "repo-1",
            {"subject_public_key": bob["public_key_pem"], "role": "contributor"},
        )
        block, result = self.mine_and_submit(4, parent_hash, [grant])
        self.assertTrue(result["accepted"])
        parent_hash = block["hash_hex"]

        change = self.signed_transaction("FILE_CHANGE", bob, "repo-1", {"path": "README.md"})
        block, result = self.mine_and_submit(5, parent_hash, [change], bob)
        self.assertTrue(result["accepted"])
        parent_hash = block["hash_hex"]

        self.engine = None
        import gc

        gc.collect()
        self.engine = goc_core.Engine(self.chain_path, "authorization-test", "L1", "")
        self.assertEqual(self.engine.tip_hash(), parent_hash)

        revoke = self.signed_transaction(
            "ACCESS_REVOKE", self.alice, "repo-1", {"subject_public_key": bob["public_key_pem"]}
        )
        block, result = self.mine_and_submit(6, parent_hash, [revoke])
        self.assertTrue(result["accepted"])
        parent_hash = block["hash_hex"]
        change = self.signed_transaction("FILE_CHANGE", bob, "repo-1", {"path": "again"})
        _, result = self.mine_and_submit(7, parent_hash, [change], bob)
        self.assertFalse(result["accepted"])

        changed_target = self.mine_and_submit(7, parent_hash, [], self.alice, "e" * 64)
        self.assertFalse(changed_target[1]["accepted"])


if __name__ == "__main__":
    unittest.main()