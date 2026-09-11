"""Cross-cutting building blocks: configuration, roles, hashing, helpers."""

from app.core.config import settings
from app.core.roles import Permission, Role, has_permission

__all__ = ["settings", "Role", "Permission", "has_permission"]
