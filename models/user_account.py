"""
AgentLedger — UserAccount ORM model (Phase 3)
"""
from sqlalchemy import BigInteger, Column, DateTime, SmallInteger, String, func

from database.connection import Base


class UserRole:
    BOSS         = "BOSS"
    ACCOUNTANT   = "ACCOUNTANT"
    DEPT_MANAGER = "DEPT_MANAGER"

    ALL = {BOSS, ACCOUNTANT, DEPT_MANAGER}


class UserAccount(Base):
    __tablename__ = "user_account"

    user_id       = Column(BigInteger,  primary_key=True, autoincrement=True)
    username      = Column(String(50),  nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    display_name  = Column(String(100), nullable=False)
    role          = Column(String(20),  nullable=False, default=UserRole.ACCOUNTANT)
    department_id = Column(BigInteger,  nullable=True)   # FK added in task 3
    is_active     = Column(SmallInteger, nullable=False, default=1)
    last_login_at = Column(DateTime,    nullable=True)
    created_at    = Column(DateTime,    nullable=False, server_default=func.now())
    updated_at    = Column(DateTime,    nullable=False, server_default=func.now(),
                           onupdate=func.now())
