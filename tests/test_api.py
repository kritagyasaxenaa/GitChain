from __future__ import annotations

import json
import unittest

from fastapi.testclient import TestClient

from gitchain.api import create_app
from gitchain.cli import _is_loopback, _write_secret
from gitchain.config import Settings


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


if __name__ == "__main__":
    unittest.main()