from sqlalchemy import BigInteger, String, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database.connection import Base


class AuditAction:
    CREATE        = "CREATE"
    UPDATE        = "UPDATE"
    DELETE        = "DELETE"
    STATUS_CHANGE = "STATUS_CHANGE"


class AuditLog(Base):
    __tablename__ = "audit_log"

    log_id:       Mapped[int]       = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_name:   Mapped[str]       = mapped_column(String(50),  nullable=False)
    record_id:    Mapped[str]       = mapped_column(String(50),  nullable=False)
    action:       Mapped[str]       = mapped_column(String(20),  nullable=False)
    user_id:      Mapped[int | None]= mapped_column(BigInteger,  nullable=True)
    username:     Mapped[str | None]= mapped_column(String(50),  nullable=True)
    before_value                    = mapped_column(JSON,         nullable=True)
    after_value                     = mapped_column(JSON,         nullable=True)
    description:  Mapped[str | None]= mapped_column(String(500), nullable=True)
    ip_address:   Mapped[str | None]= mapped_column(String(45),  nullable=True)
    created_at                      = mapped_column(DateTime, nullable=False, server_default=func.now())
