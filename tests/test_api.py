from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

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

    def blocks_after_common_ancestor_json(self, locator, max_blocks=512):
        return json.dumps([{"hash_hex": "b" * 64}])

    def submit_block(self, block_json):
        block = json.loads(block_json)
        return {
            "accepted": block.get("valid", False),
            "reason": "invalid block" if not block.get("valid", False) else "",
            "tip_height": 3,
        }


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        settings = Settings(environment="test", api_token="test-token")
        self.app = create_app(settings, engine_factory=lambda _: FakeEngine())
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)

    async def test_health_chain_and_sync_routes(self):
        self.assertEqual((await self.client.get("/health/live")).json(), {"status": "ok"})
        self.assertEqual((await self.client.get("/health/ready")).status_code, 200)
        self.assertEqual((await self.client.get("/chain/status")).json()["chain_id"], "test-chain")
        self.assertEqual((await self.client.get("/chain/locator")).json()["locator"], ["a" * 64])
        blocks = await self.client.post("/chain/blocks-after", json={"locator": ["a" * 64]})
        self.assertEqual(blocks.json(), [{"hash_hex": "b" * 64}])

    async def test_block_read_and_write_auth(self):
        found = await self.client.get(f"/blocks/{'a' * 64}")
        missing = await self.client.get(f"/blocks/{'c' * 64}")
        self.assertEqual(found.status_code, 200)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual((await self.client.post("/blocks", json={"block": {"valid": True, "transactions": []}})).status_code, 401)
        accepted = await self.client.post(
            "/blocks",
            json={"block": {"valid": True, "transactions": []}},
            headers={"Authorization": "Bearer test-token"},
        )
        rejected = await self.client.post(
            "/blocks",
            json={"block": {"valid": False, "transactions": []}},
            headers={"Authorization": "Bearer test-token"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(rejected.status_code, 422)

    async def test_peer_ingress_requires_enabled_peer_mode(self):
        settings = Settings(environment="test", p2p_enabled=True)
        app = create_app(settings, engine_factory=lambda _: FakeEngine())
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post("/peer/blocks", json={"block": {"valid": True, "transactions": []}})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()["accepted"])

    async def test_input_validation(self):
        self.assertEqual((await self.client.get("/chain/locator?limit=257")).status_code, 422)
        self.assertEqual((await self.client.get("/blocks/not-a-hash")).status_code, 422)
        self.assertEqual((await self.client.post("/chain/blocks-after", json={"locator": ["x"] * 257})).status_code, 422)
        self.assertEqual((await self.client.post("/chain/blocks-after", json={"locator": [], "limit": 513})).status_code, 422)
        self.assertEqual((await self.client.post("/peer/blocks", json={"block": {"transactions": []}})).status_code, 404)
        too_many_transactions = await self.client.post(
            "/blocks", json={"block": {"transactions": [{}] * 1001}}, headers={"Authorization": "Bearer test-token"}
        )
        too_large = await self.client.post(
            "/chain/blocks-after",
            content=b" " * (2 * 1024 * 1024 + 1),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(too_many_transactions.status_code, 422)
        self.assertEqual(too_large.status_code, 413)


class CliTests(unittest.TestCase):
    def test_p2p_configuration_requires_supported_storage_and_peer_urls(self):
        settings = Settings(
            environment="production",
            api_token="node-token",
            p2p_enabled=True,
            peers=("https://seed.example",),
        )
        self.assertTrue(settings.p2p_enabled)
        with self.assertRaisesRegex(ValueError, "PostgreSQL projection"):
            Settings(p2p_enabled=True, postgres_dsn="postgresql://db")
        with self.assertRaisesRegex(ValueError, r"base HTTP\(S\) URLs"):
            Settings(p2p_enabled=True, peers=("seed.example",))
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            Settings(environment="production", api_token="node-token", p2p_enabled=True, peers=("http://seed.example",))

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

    def test_accumulated_work_selects_a_heavier_fork_and_recovers(self):
        self.alice = self.new_keys()
        bob = self.new_keys()

        genesis, result = self.mine_and_submit(0, "")
        self.assertTrue(result["accepted"])
        genesis_hash = genesis["hash_hex"]

        first_a, result = self.mine_and_submit(1, genesis_hash, producer_keys=self.alice)
        self.assertTrue(result["accepted"])
        second_a, result = self.mine_and_submit(2, first_a["hash_hex"], producer_keys=self.alice)
        self.assertTrue(result["accepted"])
        self.assertEqual(self.engine.tip_hash(), second_a["hash_hex"])

        first_b, result = self.mine_and_submit(1, genesis_hash, producer_keys=bob)
        self.assertTrue(result["accepted"])
        parent_hash = first_b["hash_hex"]
        for height in range(2, 7):
            block, result = self.mine_and_submit(height, parent_hash, producer_keys=bob)
            self.assertTrue(result["accepted"])
            parent_hash = block["hash_hex"]
        self.assertEqual(self.engine.tip_hash(), parent_hash)
        self.assertEqual(self.engine.tip_height(), 6)
        self.assertEqual(self.engine.locator(2)[-1], genesis_hash)
        self.assertEqual(len(json.loads(self.engine.blocks_after_common_ancestor_json([genesis_hash], 2))), 2)
        self.assertIsNotNone(json.loads(self.engine.get_block_json(second_a["hash_hex"])))

        self.engine = None
        import gc

        gc.collect()
        self.engine = goc_core.Engine(self.chain_path, "authorization-test", "L1", "")
        self.assertEqual(self.engine.tip_hash(), parent_hash)


if __name__ == "__main__":
    unittest.main()
