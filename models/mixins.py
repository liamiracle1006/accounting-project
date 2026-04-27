"""
AgentLedger V4.0 — TenantMixin

All business ORM models inherit from this mixin to gain:
  - tenant_id      : top-level tenant isolation
  - account_set_id : per-account-set isolation (a tenant can have multiple books)

The database/connection.py interceptor automatically injects filters for both
columns on every SELECT that touches a TenantMixin model, using the active
TenantContext stored in a contextvars.ContextVar.
"""
from sqlalchemy import BigInteger
from sqlalchemy.orm import Mapped, mapped_column


class TenantMixin:
    """Mixin — adds tenant_id + account_set_id to any ORM model."""

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True,
        comment="FK → tenant.tenant_id — top-level tenant isolation"
    )
    account_set_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True,
        comment="FK → account_set.account_set_id — per-book isolation"
    )
