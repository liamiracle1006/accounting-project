"""
AgentLedger V4.0 — AccountingPeriod ORM model
"""
from sqlalchemy import BigInteger, Column, DateTime, Integer, String, func

from database.connection import Base
from models.mixins import TenantMixin


class PeriodStatus:
    OPEN   = "OPEN"    # 可以继续录入凭证
    CLOSED = "CLOSED"  # 已月末结账，禁止修改


class AccountingPeriod(TenantMixin, Base):
    __tablename__ = "accounting_period"

    period_id          = Column(BigInteger,   primary_key=True, autoincrement=True)
    year               = Column(Integer,      nullable=False)
    month              = Column(Integer,      nullable=False)   # 1-12
    status             = Column(String(10),   nullable=False, default=PeriodStatus.OPEN)
    closed_at          = Column(DateTime,     nullable=True)
    closed_by          = Column(BigInteger,   nullable=True)    # FK → user_account.user_id
    closing_voucher_id = Column(BigInteger,   nullable=True)    # FK → voucher_header
    created_at         = Column(DateTime,     nullable=False, server_default=func.now())
