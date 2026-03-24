from sqlalchemy import String, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database.connection import Base


class AccountSubject(Base):
    __tablename__ = "account_subject"

    subject_code: Mapped[str] = mapped_column(String(10), primary_key=True)
    subject_name: Mapped[str] = mapped_column(String(100), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(20),  nullable=False)
    direction:    Mapped[str] = mapped_column(String(10),  nullable=False)  # DEBIT / CREDIT
    is_active:    Mapped[int] = mapped_column(default=1)
    created_at    = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return f"<AccountSubject {self.subject_code} {self.subject_name}>"
