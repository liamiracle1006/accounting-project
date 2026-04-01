"""
AgentLedger V4.0 — ExpenseRequest ORM model
"""
from sqlalchemy import BigInteger, Column, DateTime, Numeric, String, Text, func

from database.connection import Base
from models.mixins import TenantMixin


class ExpenseStatus:
    PENDING  = "PENDING"    # 已提交，等待审批
    APPROVED = "APPROVED"   # 审批通过，进入财务记账队列
    REJECTED = "REJECTED"   # 驳回，申请人需修改重提


class ExpenseRequest(TenantMixin, Base):
    __tablename__ = "expense_request"

    request_id    = Column(BigInteger,    primary_key=True, autoincrement=True)
    applicant_id  = Column(BigInteger,    nullable=False)   # FK → user_account
    dept_id       = Column(BigInteger,    nullable=True)    # FK → department
    title         = Column(String(200),   nullable=False)
    amount        = Column(Numeric(18, 2), nullable=False)
    expense_type  = Column(String(100),   nullable=False)   # 差旅/办公/采购/其他
    description   = Column(Text,          nullable=True)
    status        = Column(String(20),    nullable=False, default=ExpenseStatus.PENDING)
    reviewer_id   = Column(BigInteger,    nullable=True)    # 审批人 user_id
    review_note   = Column(Text,          nullable=True)    # 审批备注
    reviewed_at   = Column(DateTime,      nullable=True)
    record_id     = Column(BigInteger,    nullable=True)    # 通过后关联的 operational_record
    created_at    = Column(DateTime,      nullable=False, server_default=func.now())
    updated_at    = Column(DateTime,      nullable=False, server_default=func.now(),
                           onupdate=func.now())
