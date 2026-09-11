"""Data access: SQL in, model objects out."""

from app.repositories.user_repository import UserRepository, user_repository

__all__ = ["UserRepository", "user_repository"]
