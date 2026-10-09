# GitHub-on-Chain

A starter implementation of the GitHub-on-Chain architecture described in the design spec.

This project provides:

- FastAPI application layer for repository and user management
- PostgreSQL-backed persistence for entities and authorization data
- C++ transaction validation/hash logic service
- Clear separation between application API and blockchain logic

## Architecture

- API: FastAPI
- Persistence: PostgreSQL
- Logic service: C++ command-line validator/hash utility
- Runtime orchestration: Docker Compose

## Quick start

1. Build the C++ logic service:

   ```bash
   cd cpp_logic
   cmake -S . -B build
   cmake --build build
   ```

2. Start PostgreSQL:

   ```bash
   docker compose up -d db
   ```

3. Install Python dependencies:

   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

4. Start the API:

   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

5. Open the docs:

   http://localhost:8000/docs

## Example workflow

- Register a user
- Create a repository
- Add a contributor or admin role
- Submit a Git-style transaction
- Verify the generated hash through the C++ logic layer

## Notes

This is intentionally a production-oriented starter rather than a fully complete blockchain implementation. It captures the core design boundaries described in the specification and gives a workable foundation for protocol extension.
