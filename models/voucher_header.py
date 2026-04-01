from decimal import Decimal
from sqlalchemy import BigInteger, String, Date, DateTime, Numeric, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.connection import Base
from models.mixins import TenantMixin


class VoucherReviewStatus:
    DRAFT          = "DRAFT"           # 草稿（AI自动生成，未审核）
    PENDING_REVIEW = "PENDING_REVIEW"  # 提交财务审核
    POSTED         = "POSTED"          # 审核通过，正式入账
    REJECTED       = "REJECTED"        # 财务驳回


class VoucherHeader(TenantMixin, Base):
    __tablename__ = "voucher_header"

    voucher_id:   Mapped[int]     = mapped_column(primary_key=True, autoincrement=True)
    record_id:    Mapped[int]     = mapped_column(ForeignKey("operational_record.record_id"),
                                                  nullable=False)
    voucher_date  = mapped_column(Date, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    memo:         Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_status = mapped_column(String(20), nullable=False,
                                  default=VoucherReviewStatus.DRAFT)
    reviewer_id   = mapped_column(BigInteger, nullable=True)   # FK → user_account
    review_note   = mapped_column(String(500), nullable=True)
    reviewed_at   = mapped_column(DateTime, nullable=True)
    created_at    = mapped_column(DateTime, server_default=func.now())

    lines = relationship("VoucherLine", back_populates="voucher",
                         cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<VoucherHeader {self.voucher_id} amount={self.total_amount}>"
