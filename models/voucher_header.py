from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, Integer, String, Date, DateTime, Numeric, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.connection import Base
from models.mixins import TenantMixin


class VoucherReviewStatus:
    DRAFT          = "DRAFT"           # 草稿（AI自动生成 / 手工新建，未提交）
    PENDING_REVIEW = "PENDING_REVIEW"  # 已提交财务审核，等待审核人操作
    POSTED         = "POSTED"          # 审核通过，正式入账（AuditGuard 防篡改）
    REJECTED       = "REJECTED"        # 财务驳回，需修改后重新提交


class VoucherHeader(TenantMixin, Base):
    __tablename__ = "voucher_header"

    voucher_id:    Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    record_id:     Mapped[int]      = mapped_column(ForeignKey("operational_record.record_id"),
                                                    nullable=False)
    voucher_date   = mapped_column(Date, nullable=False)
    voucher_number = mapped_column(Integer, nullable=True)          # 期间内连续序号（整理前可为 null）
    voucher_word   = mapped_column(String(10), nullable=True,
                                   default="记")                    # 凭证字：记/收/付/转
    total_amount:  Mapped[Decimal]  = mapped_column(Numeric(18, 2), nullable=False)
    memo:          Mapped[str|None] = mapped_column(String(500), nullable=True)
    review_status  = mapped_column(String(20), nullable=False,
                                   default=VoucherReviewStatus.DRAFT)
    creator_id     = mapped_column(BigInteger, nullable=True)       # 制单人 FK → user_account
    reviewer_id    = mapped_column(BigInteger, nullable=True)       # 审核人 FK → user_account
    review_note    = mapped_column(String(500), nullable=True)
    reviewed_at    = mapped_column(DateTime, nullable=True)
    is_deleted:    Mapped[bool]     = mapped_column(Boolean, nullable=False,
                                                    default=False)  # 软删除标志
    created_at     = mapped_column(DateTime, server_default=func.now())

    lines = relationship("VoucherLine", back_populates="voucher",
                         cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<VoucherHeader {self.voucher_id} amount={self.total_amount}>"
