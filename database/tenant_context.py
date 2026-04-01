"""
AgentLedger V4.0 — Tenant context (per-request isolation)

Uses Python contextvars so each async/thread request carries its own
tenant identity without leaking across requests.

Usage in FastAPI middleware:
    from database.tenant_context import set_current_tenant, TenantContext
    set_current_tenant(TenantContext(tenant_id=1, account_set_id=2))

The SQLAlchemy interceptor in database/connection.py reads this context
and automatically injects tenant_id + account_set_id filters on every
ORM SELECT that touches a TenantMixin model.
"""
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantContext:
    tenant_id: int
    account_set_id: int | None = None   # None = admin view (all account sets)


_current_tenant: ContextVar[TenantContext | None] = ContextVar(
    "_current_tenant", default=None
)


def get_current_tenant() -> TenantContext | None:
    return _current_tenant.get()


def set_current_tenant(ctx: TenantContext) -> None:
    _current_tenant.set(ctx)


def clear_current_tenant() -> None:
    _current_tenant.set(None)
