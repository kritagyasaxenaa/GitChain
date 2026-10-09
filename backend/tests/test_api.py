import os
import uuid

os.environ["DATABASE_URL"] = "sqlite:///./test_github_on_chain.db"

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)
client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_user_repository_and_transaction_flow():
    username = f"alice-{uuid.uuid4().hex[:8]}"
    public_key = f"pubkey-{uuid.uuid4().hex[:8]}"

    user_response = client.post(
        "/users/register",
        json={"username": username, "public_key": public_key},
    )
    assert user_response.status_code == 200

    repo_response = client.post(
        "/repositories",
        json={"name": "Demo Repo", "creator_id": user_response.json()["id"]},
    )
    assert repo_response.status_code == 200
    repo_id = repo_response.json()["id"]

    second_user_response = client.post(
        "/users/register",
        json={"username": f"bob-{uuid.uuid4().hex[:8]}", "public_key": f"pubkey-{uuid.uuid4().hex[:8]}"},
    )
    assert second_user_response.status_code == 200

    role_response = client.post(
        f"/repositories/{repo_id}/roles",
        json={"user_id": second_user_response.json()["id"], "role": "admin"},
    )
    assert role_response.status_code == 200

    tx_response = client.post(
        f"/repositories/{repo_id}/transactions",
        json={
            "repository_id": repo_id,
            "author_public_key": public_key,
            "commit_id": "abc123",
            "parent_commit": None,
            "operation": "ADD",
            "payload": "file: main.cpp\ncontent: int main(){return 0;}",
        },
    )
    assert tx_response.status_code == 200
    assert "tx_hash" in tx_response.json()
