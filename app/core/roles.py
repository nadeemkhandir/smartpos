"""
Roles and permissions.

A role is stored in the database as a plain lowercase string so the column stays
readable in any SQLite browser. Screens should never test the string directly —
ask ``Role.can(role, Permission.X)`` instead, so adding a role later means
editing one table here rather than hunting through the UI.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    """Every account type SmartPOS recognises."""

    ADMIN = "admin"
    MANAGER = "manager"
    CASHIER = "cashier"
    INVENTORY = "inventory"
    ACCOUNTANT = "accountant"
    VIEWER = "viewer"

    @property
    def label(self) -> str:
        """Title shown in the UI, e.g. ``Inventory Clerk``."""
        return _LABELS[self]

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self]

    @classmethod
    def choices(cls) -> list["Role"]:
        return list(cls)

    @classmethod
    def values(cls) -> list[str]:
        return [role.value for role in cls]

    @classmethod
    def parse(cls, value: "str | Role | None", default: "Role | None" = None) -> "Role":
        """Turn a stored string into a Role, tolerating case and stray spaces."""
        if isinstance(value, cls):
            return value
        if value:
            try:
                return cls(str(value).strip().lower())
            except ValueError:
                pass
        if default is not None:
            return default
        raise ValueError(f"Unknown role: {value!r}")

    def can(self, permission: "Permission") -> bool:
        return permission in ROLE_PERMISSIONS[self]


class Permission(str, Enum):
    """Individual capabilities a role may be granted."""

    # Point of sale
    SELL = "sell"
    REFUND = "refund"
    APPLY_DISCOUNT = "apply_discount"
    VOID_SALE = "void_sale"
    OPEN_CASH_DRAWER = "open_cash_drawer"

    # Inventory
    VIEW_INVENTORY = "view_inventory"
    MANAGE_PRODUCTS = "manage_products"
    ADJUST_STOCK = "adjust_stock"
    MANAGE_SUPPLIERS = "manage_suppliers"
    RECEIVE_PURCHASE = "receive_purchase"

    # Money
    VIEW_REPORTS = "view_reports"
    VIEW_FINANCIALS = "view_financials"
    CLOSE_REGISTER = "close_register"

    # Administration
    MANAGE_USERS = "manage_users"
    APPROVE_REGISTRATIONS = "approve_registrations"
    RESET_PASSWORDS = "reset_passwords"
    MANAGE_SETTINGS = "manage_settings"
    VIEW_AUDIT_LOG = "view_audit_log"


_LABELS = {
    Role.ADMIN: "Administrator",
    Role.MANAGER: "Store Manager",
    Role.CASHIER: "Cashier",
    Role.INVENTORY: "Inventory Clerk",
    Role.ACCOUNTANT: "Accountant",
    Role.VIEWER: "Viewer",
}

_DESCRIPTIONS = {
    Role.ADMIN: "Full control, including users, settings and audit history.",
    Role.MANAGER: "Runs the store: sales, stock, staff passwords and reports.",
    Role.CASHIER: "Serves customers at the till.",
    Role.INVENTORY: "Receives stock, maintains products and suppliers.",
    Role.ACCOUNTANT: "Reads sales and financial reports, closes the register.",
    Role.VIEWER: "Read-only access for training or oversight.",
}

_ALL = set(Permission)

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ADMIN: set(_ALL),
    Role.MANAGER: {
        Permission.SELL,
        Permission.REFUND,
        Permission.APPLY_DISCOUNT,
        Permission.VOID_SALE,
        Permission.OPEN_CASH_DRAWER,
        Permission.VIEW_INVENTORY,
        Permission.MANAGE_PRODUCTS,
        Permission.ADJUST_STOCK,
        Permission.MANAGE_SUPPLIERS,
        Permission.RECEIVE_PURCHASE,
        Permission.VIEW_REPORTS,
        Permission.VIEW_FINANCIALS,
        Permission.CLOSE_REGISTER,
        Permission.APPROVE_REGISTRATIONS,
        Permission.RESET_PASSWORDS,
        Permission.VIEW_AUDIT_LOG,
    },
    Role.CASHIER: {
        Permission.SELL,
        Permission.OPEN_CASH_DRAWER,
        Permission.VIEW_INVENTORY,
    },
    Role.INVENTORY: {
        Permission.VIEW_INVENTORY,
        Permission.MANAGE_PRODUCTS,
        Permission.ADJUST_STOCK,
        Permission.MANAGE_SUPPLIERS,
        Permission.RECEIVE_PURCHASE,
    },
    Role.ACCOUNTANT: {
        Permission.VIEW_INVENTORY,
        Permission.VIEW_REPORTS,
        Permission.VIEW_FINANCIALS,
        Permission.CLOSE_REGISTER,
    },
    Role.VIEWER: {
        Permission.VIEW_INVENTORY,
        Permission.VIEW_REPORTS,
    },
}


def has_permission(role: "str | Role | None", permission: Permission) -> bool:
    """Permission check that never raises on unknown input — it just says no."""
    try:
        return Role.parse(role).can(permission)
    except ValueError:
        return False
