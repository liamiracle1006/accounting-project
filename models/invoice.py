from decimal import Decimal
from sqlalchemy import BigInteger, String, Date, DateTime, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column
from database.connection import Base


class InvoiceType:
    INPUT  = "INPUT"   # 进项（采购取得）
    OUTPUT = "OUTPUT"  # 销项（销售开出）


class InvoiceStatus:
    UNVERIFIED = "UNVERIFIED"  # 待验真
    VERIFIED   = "VERIFIED"    # 已验真（税务局接口或人工确认）
    INVALID    = "INVALID"     # 作废


class InvoiceSource:
    MANUAL = "MANUAL"  # 手工录入
    OCR    = "OCR"     # 扫描/图片识别


class Invoice(Base):
    __tablename__ = "invoice"

    invoice_id:      Mapped[int]          = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    invoice_type:    Mapped[str]          = mapped_column(String(20),  nullable=False)
    invoice_code:    Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    invoice_number:  Mapped[str]          = mapped_column(String(20),  nullable=False)
    invoice_date:    Mapped[Date]         = mapped_column(Date,         nullable=False)
    seller_name:     Mapped[str | None]   = mapped_column(String(200), nullable=True)
    seller_tax_id:   Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    buyer_name:      Mapped[str | None]   = mapped_column(String(200), nullable=True)
    buyer_tax_id:    Mapped[str | None]   = mapped_column(String(20),  nullable=True)
    subtotal_amount: Mapped[Decimal]      = mapped_column(Numeric(18, 2), nullable=False)
    tax_rate:        Mapped[Decimal]      = mapped_column(Numeric(5, 4),  nullable=False, default=Decimal("0"))
    tax_amount:      Mapped[Decimal]      = mapped_column(Numeric(18, 2), nullable=False)
    total_amount:    Mapped[Decimal]      = mapped_column(Numeric(18, 2), nullable=False)
    items_summary:   Mapped[str | None]   = mapped_column(String(500), nullable=True)
    voucher_id:      Mapped[int | None]   = mapped_column(BigInteger,  nullable=True)
    status:          Mapped[str]          = mapped_column(String(20),  nullable=False, default=InvoiceStatus.UNVERIFIED)
    source:          Mapped[str]          = mapped_column(String(20),  nullable=False, default=InvoiceSource.MANUAL)
    image_path:      Mapped[str | None]   = mapped_column(String(500), nullable=True)
    created_by:      Mapped[int | None]   = mapped_column(BigInteger,  nullable=True)
    created_at                            = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at                            = mapped_column(DateTime, nullable=False, server_default=func.now(),
                                                          onupdate=func.now())
