from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    public_key: str = Field(..., min_length=8)


class UserRead(BaseModel):
    id: str
    username: str
    public_key: str
    created_at: datetime


class RepositoryCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=128)
    creator_id: str


class RepositoryRead(BaseModel):
    id: str
    name: str
    slug: str
    creator_id: str
    created_at: datetime


class RoleAssignmentCreate(BaseModel):
    user_id: str
    role: Literal["creator", "admin", "contributor"]


class GitTransactionCreate(BaseModel):
    repository_id: str
    author_public_key: str
    commit_id: str
    parent_commit: str | None = None
    operation: Literal["ADD", "MODIFY", "DELETE", "RENAME"]
    payload: str


class GitTransactionRead(BaseModel):
    id: str
    repository_id: str
    author_public_key: str
    commit_id: str
    parent_commit: str | None
    operation: str
    payload: str
    tx_hash: str
    created_at: datetime


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
