"""
AgentLedger V4.0 — Tenant model

Top-level SaaS tenant.  Each tenant maps to one company/organisation
that has purchased the service.  A tenant can own multiple AccountSets
(e.g. HQ books + subsidiary books).
"""
from sqlalchemy import BigInteger, String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class TenantStatus:
    TRIAL     = "TRIAL"      # 试用期（功能受限）
    ACTIVE    = "ACTIVE"     # 正常使用
    SUSPENDED = "SUSPENDED"  # 欠费/违规暂停


class Tenant(Base):
    __tablename__ = "tenant"

    tenant_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True
    )
    tenant_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="企业/租户名称"
    )
    contact_email: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="主联系人邮箱"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=TenantStatus.TRIAL,
        comment="TRIAL / ACTIVE / SUSPENDED"
    )
    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<Tenant id={self.tenant_id} name='{self.tenant_name}' status={self.status}>"
