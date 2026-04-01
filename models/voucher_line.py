from decimal import Decimal
from sqlalchemy import String, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.connection import Base
from models.mixins import TenantMixin


class VoucherLine(TenantMixin, Base):
    __tablename__ = "voucher_line"

    line_id:             Mapped[int]     = mapped_column(primary_key=True, autoincrement=True)
    voucher_id:          Mapped[int]     = mapped_column(ForeignKey("voucher_header.voucher_id"),
                                                         nullable=False)
    subject_code:        Mapped[str]     = mapped_column(ForeignKey("account_subject.subject_code"),
                                                         nullable=False)
    direction:           Mapped[str]     = mapped_column(String(10), nullable=False)  # DEBIT/CREDIT
    amount:              Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    auxiliary_entity_id: Mapped[int | None] = mapped_column(
                             ForeignKey("auxiliary_entity.entity_id"), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(200), nullable=True)

    voucher = relationship("VoucherHeader", back_populates="lines")

    def __repr__(self) -> str:
        return (f"<VoucherLine {self.line_id} {self.direction} "
                f"{self.subject_code} {self.amount}>")
