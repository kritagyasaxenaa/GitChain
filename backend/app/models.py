from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    public_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    repositories: Mapped[list["Repository"]] = relationship(back_populates="creator")
    assignments: Mapped[list["RoleAssignment"]] = relationship(back_populates="user")


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    creator_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    creator: Mapped[User] = relationship(back_populates="repositories")
    assignments: Mapped[list["RoleAssignment"]] = relationship(back_populates="repository")
    transactions: Mapped[list["GitTransaction"]] = relationship(back_populates="repository")


class RoleAssignment(Base):
    __tablename__ = "role_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="assignments")
    user: Mapped[User] = relationship(back_populates="assignments")


class GitTransaction(Base):
    __tablename__ = "git_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), nullable=False)
    author_public_key: Mapped[str] = mapped_column(String(255), nullable=False)
    commit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_commit: Mapped[str | None] = mapped_column(String(128), nullable=True)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    tx_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    repository: Mapped[Repository] = relationship(back_populates="transactions")
