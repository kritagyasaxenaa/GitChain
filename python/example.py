"""Smoke-test examples for the goc_core pybind11 extension.

Build the extension first, then make sure the directory containing goc_core*.so
(or goc_core*.pyd on Windows) is on PYTHONPATH.
"""
import json
import goc_core

# Generate and keep the private key securely; do not log it in a real service.
identity = json.loads(goc_core.create_local_identity("alice"))
print("identity_id:", identity["identity_id"])
print("public key:", identity["keys"]["public_key_pem"])

print("SHA-256:", goc_core.sha256("hello"))
print("Engine methods: status, submit_block, tip_hash, tip_height, locator, get_block_json")

# Example engine construction (RocksDB directory must be writable).
# engine = goc_core.Engine("./data/l1", "L1", "L1")
# print(engine.status())
