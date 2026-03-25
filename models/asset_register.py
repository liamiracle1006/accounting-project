"""
AgentLedger — AssetRegister model

固定资产台账。每当老板决策"购入固定资产"后，除生成凭证外，
资产同步进入此表，系统后续每月自动计提折旧。

depreciation_method 枚举：
  STRAIGHT_LINE  — 直线法（年限平均法）
  ACCELERATED    — 加速折旧（双倍余额递减法，后两年切直线）
  ONE_TIME       — 一次性扣除（当月全额计提，台账保留资产记录）

status 枚举：
  IN_USE           — 使用中
  FULLY_DEPRECIATED — 已全额折旧
  DISPOSED          — 已处置
"""
from datetime import date

from sqlalchemy import BigInteger, String, Numeric, Date, DateTime, func, Text
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base


class DepreciationMethod:
    STRAIGHT_LINE = "STRAIGHT_LINE"
    ACCELERATED   = "ACCELERATED"
    ONE_TIME      = "ONE_TIME"


class AssetStatus:
    IN_USE            = "IN_USE"
    FULLY_DEPRECIATED = "FULLY_DEPRECIATED"
    DISPOSED          = "DISPOSED"


class AssetRegister(Base):
    __tablename__ = "asset_register"

    asset_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    voucher_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False,
        comment="FK → voucher_header（购入凭证）"
    )

    decision_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True,
        comment="FK → boss_decision_log（来源决策，手动录入时为空）"
    )

    asset_name: Mapped[str] = mapped_column(
        String(200), nullable=False,
        comment="资产名称，如'激光切割机'、'服务器'"
    )

    asset_category: Mapped[str] = mapped_column(
        String(50), nullable=False, default="通用设备",
        comment="资产分类：电子设备/通用机械/车辆/建筑装修/通用设备"
    )

    original_value: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False,
        comment="原值（购入金额）"
    )

    net_salvage_value: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0.00,
        comment="预计净残值（通常为原值5%，一次性扣除填0）"
    )

    depreciation_method: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="STRAIGHT_LINE / ACCELERATED / ONE_TIME"
    )

    useful_life_months: Mapped[int] = mapped_column(
        nullable=False,
        comment="预计使用月数（一次性扣除填1）"
    )

    monthly_depreciation: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False,
        comment="月折旧额（由系统根据方法计算后写入，一次性扣除=原值）"
    )

    accumulated_depreciation: Mapped[float] = mapped_column(
        Numeric(18, 2), nullable=False, default=0.00,
        comment="累计已计提折旧"
    )

    depreciation_months_elapsed: Mapped[int] = mapped_column(
        nullable=False, default=0,
        comment="已折旧月数"
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AssetStatus.IN_USE,
        comment="IN_USE / FULLY_DEPRECIATED / DISPOSED"
    )

    purchase_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="购入日期（凭证日期）"
    )

    depreciation_start_month: Mapped[str] = mapped_column(
        String(7), nullable=False,
        comment="开始折旧的会计期间，格式 YYYY-MM（购入次月起折旧）"
    )

    notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="备注（如政策依据、税务备案信息）"
    )

    created_at = mapped_column(DateTime, server_default=func.now())
    updated_at = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    @property
    def net_book_value(self) -> float:
        """账面净值 = 原值 - 累计折旧"""
        return float(self.original_value) - float(self.accumulated_depreciation)

    def __repr__(self) -> str:
        return (
            f"<AssetRegister id={self.asset_id} "
            f"name='{self.asset_name}' value={self.original_value} "
            f"method={self.depreciation_method}>"
        )
