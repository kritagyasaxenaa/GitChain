import re
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, engine, get_db
from app.models import GitTransaction, Repository, RoleAssignment, User
from app.schemas import (
    GitTransactionCreate,
    GitTransactionRead,
    HealthResponse,
    RepositoryCreate,
    RepositoryRead,
    RoleAssignmentCreate,
    UserCreate,
    UserRead,
)
from app.services.logic_bridge import compute_transaction_hash

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "repo"


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", app_name=settings.app_name, environment=settings.app_env)


@app.post("/users/register", response_model=UserRead)
def register_user(payload: UserCreate, db: Annotated[Session, Depends(get_db)]):
    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists")
    if db.scalar(select(User).where(User.public_key == payload.public_key)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Public key already registered")

    user = User(username=payload.username, public_key=payload.public_key)
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserRead(
        id=str(user.id),
        username=user.username,
        public_key=user.public_key,
        created_at=user.created_at,
    )


@app.get("/users/{username}", response_model=UserRead)
def get_user(username: str, db: Annotated[Session, Depends(get_db)]):
    user = db.scalar(select(User).where(User.username == username))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return UserRead(
        id=str(user.id),
        username=user.username,
        public_key=user.public_key,
        created_at=user.created_at,
    )


@app.post("/repositories", response_model=RepositoryRead)
def create_repository(payload: RepositoryCreate, db: Annotated[Session, Depends(get_db)]):
    creator = db.get(User, payload.creator_id)
    if not creator:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Creator not found")

    base_slug = _slugify(payload.name)
    slug = base_slug
    suffix = 1
    while db.scalar(select(Repository).where(Repository.slug == slug)):
        slug = f"{base_slug}-{suffix}"
        suffix += 1

    repository = Repository(name=payload.name, slug=slug, creator_id=creator.id)
    db.add(repository)
    db.flush()

    assignment = RoleAssignment(repository_id=repository.id, user_id=creator.id, role="creator")
    db.add(assignment)
    db.commit()
    db.refresh(repository)

    return RepositoryRead(
        id=str(repository.id),
        name=repository.name,
        slug=repository.slug,
        creator_id=str(repository.creator_id),
        created_at=repository.created_at,
    )


@app.post("/repositories/{repository_id}/roles")
def assign_role(repository_id: str, payload: RoleAssignmentCreate, db: Annotated[Session, Depends(get_db)]):
    repository = db.get(Repository, repository_id)
    if not repository:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    user = db.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if db.scalar(select(RoleAssignment).where(RoleAssignment.repository_id == repository.id, RoleAssignment.user_id == user.id)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User already has a role for this repository")

    assignment = RoleAssignment(repository_id=repository.id, user_id=user.id, role=payload.role)
    db.add(assignment)
    db.commit()

    return {"message": "Role assigned", "role": payload.role, "repository_id": repository_id, "user_id": payload.user_id}


@app.post("/repositories/{repository_id}/transactions", response_model=GitTransactionRead)
def create_transaction(repository_id: str, payload: GitTransactionCreate, db: Annotated[Session, Depends(get_db)]):
    repository = db.get(Repository, repository_id)
    if not repository:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    author = db.scalar(select(User).where(User.public_key == payload.author_public_key))
    if not author:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Author public key not known")

    role = db.scalar(
        select(RoleAssignment).where(
            RoleAssignment.repository_id == repository.id,
            RoleAssignment.user_id == author.id,
        )
    )
    if not role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Author has no repository role")

    logic_result = compute_transaction_hash(
        repo_id=repository_id,
        author_public_key=payload.author_public_key,
        operation=payload.operation,
        commit_id=payload.commit_id,
        payload=payload.payload,
        parent_commit=payload.parent_commit,
    )

    tx = GitTransaction(
        repository_id=repository.id,
        author_public_key=payload.author_public_key,
        commit_id=payload.commit_id,
        parent_commit=payload.parent_commit,
        operation=payload.operation,
        payload=payload.payload,
        tx_hash=logic_result["tx_hash"],
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)

    return GitTransactionRead(
        id=str(tx.id),
        repository_id=str(tx.repository_id),
        author_public_key=tx.author_public_key,
        commit_id=tx.commit_id,
        parent_commit=tx.parent_commit,
        operation=tx.operation,
        payload=tx.payload,
        tx_hash=tx.tx_hash,
        created_at=tx.created_at,
    )


@app.get("/repositories/{repository_id}/transactions", response_model=list[GitTransactionRead])
def list_transactions(repository_id: str, db: Annotated[Session, Depends(get_db)]):
    repository = db.get(Repository, repository_id)
    if not repository:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Repository not found")

    rows = db.scalars(select(GitTransaction).where(GitTransaction.repository_id == repository.id)).all()
    return [
        GitTransactionRead(
            id=str(item.id),
            repository_id=str(item.repository_id),
            author_public_key=item.author_public_key,
            commit_id=item.commit_id,
            parent_commit=item.parent_commit,
            operation=item.operation,
            payload=item.payload,
            tx_hash=item.tx_hash,
            created_at=item.created_at,
        )
        for item in rows
    ]
