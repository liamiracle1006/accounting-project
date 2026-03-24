from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database.connection import Base


class RecordStatus:
    PENDING       = "PENDING"
    PROCESSED     = "PROCESSED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class OperationalRecord(Base):
    __tablename__ = "operational_record"

    record_id:      Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_text:       Mapped[str] = mapped_column(Text, nullable=False)
    extracted_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status:         Mapped[str] = mapped_column(String(30), nullable=False,
                                                default=RecordStatus.PENDING)
    error_message:  Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at      = mapped_column(DateTime, server_default=func.now())
    updated_at      = mapped_column(DateTime, server_default=func.now(),
                                    onupdate=func.now())

    def __repr__(self) -> str:
        return f"<OperationalRecord {self.record_id} [{self.status}]>"
