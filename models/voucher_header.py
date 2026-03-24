from decimal import Decimal
from sqlalchemy import String, Date, DateTime, Numeric, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.connection import Base


class VoucherHeader(Base):
    __tablename__ = "voucher_header"

    voucher_id:   Mapped[int]     = mapped_column(primary_key=True, autoincrement=True)
    record_id:    Mapped[int]     = mapped_column(ForeignKey("operational_record.record_id"),
                                                  nullable=False)
    voucher_date  = mapped_column(Date, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    memo:         Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at    = mapped_column(DateTime, server_default=func.now())

    lines = relationship("VoucherLine", back_populates="voucher",
                         cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<VoucherHeader {self.voucher_id} amount={self.total_amount}>"
