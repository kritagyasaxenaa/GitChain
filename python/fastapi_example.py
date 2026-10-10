"""Compatibility module for existing uvicorn command lines."""

from gitchain.api import app, create_app
from gitchain.cli import main

__all__ = ["app", "create_app", "main"]

if __name__ == "__main__":
    main()
