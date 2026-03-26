"""
AgentLedger — Department ORM model (Phase 3)
"""
from sqlalchemy import BigInteger, Column, DateTime, SmallInteger, String, func

from database.connection import Base


class Department(Base):
    __tablename__ = "department"

    dept_id      = Column(BigInteger,   primary_key=True, autoincrement=True)
    dept_name    = Column(String(100),  nullable=False, unique=True)
    cost_center  = Column(String(50),   nullable=True)   # 成本中心代码，可选
    manager_id   = Column(BigInteger,   nullable=True)   # FK → user_account.user_id
    is_active    = Column(SmallInteger, nullable=False, default=1)
    created_at   = Column(DateTime,     nullable=False, server_default=func.now())
    updated_at   = Column(DateTime,     nullable=False, server_default=func.now(),
                          onupdate=func.now())
