import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CPP_BINARY = PROJECT_ROOT / "cpp_logic" / "build" / "github_on_chain_logic"


def compute_transaction_hash(repo_id: str, author_public_key: str, operation: str, commit_id: str, payload: str, parent_commit: str | None = None) -> dict:
    if not CPP_BINARY.exists():
        raise RuntimeError(
            "C++ logic binary not found. Build it with: cd cpp_logic && cmake -S . -B build && cmake --build build"
        )

    command = [
        str(CPP_BINARY),
        "--repo-id",
        repo_id,
        "--author",
        author_public_key,
        "--operation",
        operation,
        "--commit-id",
        commit_id,
        "--payload",
        payload,
    ]

    if parent_commit:
        command.extend(["--parent-commit", parent_commit])

    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)
