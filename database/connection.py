"""
AgentLedger V4.0 — SQLAlchemy engine + session factory + tenant isolation
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase, with_loader_criteria

from config.settings import DATABASE_URL, DB_ECHO


engine = create_engine(
    DATABASE_URL,
    echo=DB_ECHO,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,      # reconnect on stale connections
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── Tenant isolation interceptor ─────────────────────────────────────────────
@event.listens_for(SessionLocal, "do_orm_execute")
def _apply_tenant_filter(execute_state):
    """
    Automatically inject tenant_id (+ account_set_id when set) filters on
    every ORM SELECT that touches a TenantMixin model.

    Short-circuits on column/relationship loads to avoid recursion.
    No-ops when no TenantContext is active (e.g. background jobs, migrations).
    """
    if (
        execute_state.is_select
        and not execute_state.is_column_load
        and not execute_state.is_relationship_load
    ):
        from database.tenant_context import get_current_tenant
        ctx = get_current_tenant()
        if ctx is None:
            return

        from models.mixins import TenantMixin

        # Capture ctx by value so the lambda is safe across async boundaries
        _ctx = ctx

        def _criteria(cls):
            crit = cls.tenant_id == _ctx.tenant_id
            if _ctx.account_set_id is not None:
                crit = crit & (cls.account_set_id == _ctx.account_set_id)
            return crit

        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(TenantMixin, _criteria, include_aliases=True)
        )


def get_db():
    """FastAPI dependency — yields a DB session and guarantees cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables (used in tests / first-run bootstrap)."""
    from models import (                                         # noqa: F401
        account_subject, auxiliary_entity, tenant, account_set,
        operational_record, voucher_header, voucher_line,
        enterprise_profile, asset_register, accounting_period,
        boss_decision_log, tax_annual_plan, invoice,
        expense_request, department, user_account, audit_log,
    )
    Base.metadata.create_all(bind=engine)
