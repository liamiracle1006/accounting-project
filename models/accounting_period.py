"""
AgentLedger — AccountingPeriod ORM model (Phase 4)
"""
from sqlalchemy import BigInteger, Column, DateTime, Integer, SmallInteger, String, func

from database.connection import Base


class PeriodStatus:
    OPEN   = "OPEN"    # 可以继续录入凭证
    CLOSED = "CLOSED"  # 已月末结账，禁止修改


class AccountingPeriod(Base):
    __tablename__ = "accounting_period"

    period_id  = Column(BigInteger,   primary_key=True, autoincrement=True)
    year       = Column(Integer,      nullable=False)
    month      = Column(Integer,      nullable=False)   # 1-12
    status     = Column(String(10),   nullable=False, default=PeriodStatus.OPEN)
    closed_at  = Column(DateTime,     nullable=True)
    closed_by  = Column(BigInteger,   nullable=True)    # FK → user_account.user_id
    # 结账凭证 ID（损益结转）
    closing_voucher_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime,     nullable=False, server_default=func.now())
