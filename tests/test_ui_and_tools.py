from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from gitchain.api import create_app
from gitchain.config import Settings

try:
    import goc_core
except ImportError:
    goc_core = None


class UiAndToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.chain_path = Path(self.temp_dir.name) / "chain"
        self.settings = Settings(
            rocks_path=self.chain_path,
            chain_id="UI-TEST",
            chain_type="L1",
            environment="development",
        )
        self.app = create_app(self.settings)
        self.client_ctx = TestClient(self.app)
        self.client = self.client_ctx.__enter__()

    def tearDown(self):
        self.client_ctx.__exit__(None, None, None)
        self.temp_dir.cleanup()

    def test_ui_endpoints(self):
        # Root index
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("GitChain", resp.text)
        self.assertIn("tab-explorer", resp.text)

        # UI alias
        resp_ui = self.client.get("/ui")
        self.assertEqual(resp_ui.status_code, 200)
        self.assertIn("GitChain", resp_ui.text)

        # Static CSS and JS
        resp_css = self.client.get("/static/style.css")
        self.assertEqual(resp_css.status_code, 200)
        self.assertIn("text/css", resp_css.headers["content-type"])

        resp_js = self.client.get("/static/app.js")
        self.assertEqual(resp_js.status_code, 200)
        self.assertIn("javascript", resp_js.headers["content-type"])

    @unittest.skipIf(goc_core is None, "goc_core is required for tool and consensus tests")
    def test_identity_and_keypair_tools(self):
        # Generate keypair
        res = self.client.post("/api/tools/generate-keypair")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("public_key_pem", data)
        self.assertIn("private_key_pem", data)

        # Create identity
        res_id = self.client.post("/api/tools/create-identity", json={"username": "carol"})
        self.assertEqual(res_id.status_code, 200)
        id_data = res_id.json()
        self.assertEqual(id_data["username"], "carol")
        self.assertIn("identity_id", id_data)
        self.assertIn("keys", id_data)

    @unittest.skipIf(goc_core is None, "goc_core is required for tool and consensus tests")
    def test_sign_build_mine_verify_flow(self):
        # 1. Create identity
        id_res = self.client.post("/api/tools/create-identity", json={"username": "miner1"})
        miner = id_res.json()
        pub_key = miner["keys"]["public_key_pem"]
        priv_key = miner["keys"]["private_key_pem"]

        # 2. Sign a user registration transaction
        tx = {
            "operation": "USER_CREATE",
            "actor_public_key": pub_key,
            "repository_id": "",
            "payload": {"username": "miner1", "identity_id": miner["identity_id"]},
            "signature_hex": ""
        }
        sign_res = self.client.post("/api/tools/sign-transaction", json={
            "transaction": tx,
            "private_key_pem": priv_key
        })
        self.assertEqual(sign_res.status_code, 200)
        signed_tx = sign_res.json()["transaction"]
        self.assertTrue(len(signed_tx["signature_hex"]) > 0)

        # 3. Build genesis block
        build_res = self.client.post("/api/tools/build-block", json={
            "chain_type": "L1",
            "chain_id": "UI-TEST",
            "height": 0,
            "previous_hash": "",
            "target_hex": "f" * 64,
            "transactions": [],
            "producer_public_key": pub_key
        })
        self.assertEqual(build_res.status_code, 200)
        block = build_res.json()["block"]

        # 4. Mine block
        mine_res = self.client.post("/api/tools/mine-block", json={
            "block": block,
            "private_key_pem": priv_key,
            "max_attempts": 1000
        })
        self.assertEqual(mine_res.status_code, 200)
        mined_block = mine_res.json()["mined_block"]
        self.assertTrue(len(mined_block["hash_hex"]) == 64)
        self.assertTrue(len(mine_res.json()["score"]) > 0)

        # 5. Verify PoW
        verify_res = self.client.post("/api/tools/verify-block", json={"block": mined_block})
        self.assertEqual(verify_res.status_code, 200)
        self.assertTrue(verify_res.json()["valid_pow"])

        # 6. Submit genesis block to chain
        submit_res = self.client.post("/blocks", json={"block": mined_block})
        self.assertEqual(submit_res.status_code, 200)
        self.assertTrue(submit_res.json()["accepted"])

        # 7. Check list blocks
        blocks_res = self.client.get("/api/chain/blocks")
        self.assertEqual(blocks_res.status_code, 200)
        blocks = blocks_res.json()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["hash_hex"], mined_block["hash_hex"])

    @unittest.skipIf(goc_core is None, "goc_core is required for tool and consensus tests")
    def test_seed_demo_chain(self):
        # Verify chain starts empty
        status_before = self.client.get("/chain/status").json()
        self.assertEqual(status_before["tip_hash"], "")
        self.assertEqual(status_before["tip_height"], 0)

        # Call seed demo
        seed_res = self.client.post("/api/chain/seed-demo")
        self.assertEqual(seed_res.status_code, 200)
        seed_data = seed_res.json()
        self.assertEqual(seed_data["tip_height"], 3)
        self.assertTrue(len(seed_data["tip_hash"]) == 64)

        # Verify blocks endpoint returns all 4 seeded blocks
        blocks_res = self.client.get("/api/chain/blocks")
        self.assertEqual(blocks_res.status_code, 200)
        blocks = blocks_res.json()
        self.assertEqual(len(blocks), 4)
        # Newest block first by default: height 3 down to 0
        self.assertEqual(blocks[0]["header"]["height"], 3)
        self.assertEqual(blocks[3]["header"]["height"], 0)

        # Calling seed demo again is idempotent
        repeat_res = self.client.post("/api/chain/seed-demo")
        self.assertEqual(repeat_res.status_code, 200)
        self.assertIn("already initialized", repeat_res.json()["message"])


if __name__ == "__main__":
    unittest.main()
