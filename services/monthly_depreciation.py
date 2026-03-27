"""
AgentLedger — MonthlyDepreciationService

每月自动计提固定资产折旧。

会计分录：
  借 管理费用 (6602)   月折旧额
  贷 累计折旧 (1602)   月折旧额

执行逻辑：
  1. 找出所有 IN_USE 资产，且 depreciation_start_month <= 当前期间
  2. 检查该资产本月是否已计提（避免重复）
  3. 按折旧方法计算本月折旧额：
     - ONE_TIME：第一个月全额，之后标记 FULLY_DEPRECIATED
     - STRAIGHT_LINE：固定月折旧额
     - ACCELERATED：双倍余额递减，后两年切直线（读取当前已折月数推算）
  4. 生成凭证，更新 asset_register 的累计折旧和已折月数
  5. 若 accumulated_depreciation >= depreciable_amount，标记 FULLY_DEPRECIATED

设计约束：
  - 幂等性：同一资产同一期间只能计提一次，重复调用安全
  - 原子性：每笔资产的凭证生成 + 台账更新在同一事务中
  - 不依赖 LLM，纯数学计算
"""
import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.asset_register import AssetRegister, AssetStatus, DepreciationMethod
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from models.account_subject import AccountSubject
from models.operational_record import OperationalRecord, RecordStatus

logger = logging.getLogger(__name__)

# 折旧计提科目
DEPRECIATION_EXPENSE_CODE = "6602"   # 管理费用（或制造费用，简化统一用管理费用）
ACCUMULATED_DEP_CODE      = "1602"   # 累计折旧


class DepreciationRunResult:
    def __init__(self):
        self.period:          str       = ""
        self.processed:       int       = 0
        self.skipped:         int       = 0
        self.fully_depreciated:int      = 0
        self.total_amount:    Decimal   = Decimal("0.00")
        self.voucher_ids:     list[int] = []
        self.errors:          list[str] = []


class MonthlyDepreciationService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def run(self, year: int, month: int) -> DepreciationRunResult:
        """
        对指定期间执行月度折旧。
        period 格式：YYYY-MM，如 "2026-03"
        """
        period = f"{year}-{month:02d}"
        result = DepreciationRunResult()
        result.period = period

        self._assert_subjects_exist()

        # 创建系统级流水记录，供本次折旧批次的所有凭证引用
        dep_record = OperationalRecord(
            raw_text = f"[系统] {period} 月度固定资产折旧计提",
            status   = RecordStatus.PROCESSED,
        )
        self._db.add(dep_record)
        self._db.flush()

        assets = (
            self._db.query(AssetRegister)
            .filter(
                AssetRegister.status == AssetStatus.IN_USE,
                AssetRegister.depreciation_start_month <= period,
            )
            .all()
        )

        for asset in assets:
            try:
                already_done = self._already_posted(asset, period)
                if already_done:
                    result.skipped += 1
                    logger.info("Asset %s already depreciated for %s, skipping", asset.asset_id, period)
                    continue

                dep_amount = self._calc_this_month(asset)
                if dep_amount <= Decimal("0.00"):
                    result.skipped += 1
                    continue

                voucher = self._post_depreciation(asset, dep_amount, period, year, month, dep_record.record_id)
                self._update_asset(asset, dep_amount)

                result.processed      += 1
                result.total_amount   += dep_amount
                result.voucher_ids.append(voucher.voucher_id)

                if asset.status == AssetStatus.FULLY_DEPRECIATED:
                    result.fully_depreciated += 1

                self._db.flush()

            except Exception as exc:
                self._db.rollback()
                msg = f"Asset {asset.asset_id} ({asset.asset_name}): {exc}"
                result.errors.append(msg)
                logger.error("Depreciation failed — %s", msg)

        self._db.commit()
        logger.info(
            "Depreciation run %s: processed=%d skipped=%d total=%.2f errors=%d",
            period, result.processed, result.skipped,
            float(result.total_amount), len(result.errors),
        )
        return result

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _calc_this_month(self, asset: AssetRegister) -> Decimal:
        """
        计算本月应计提折旧额。
        """
        depreciable = (
            Decimal(str(asset.original_value)) - Decimal(str(asset.net_salvage_value))
        )
        accumulated = Decimal(str(asset.accumulated_depreciation))
        remaining   = depreciable - accumulated

        if remaining <= Decimal("0.00"):
            return Decimal("0.00")

        method = asset.depreciation_method

        if method == DepreciationMethod.ONE_TIME:
            # 第一个月全额扣除
            return remaining

        if method == DepreciationMethod.STRAIGHT_LINE:
            monthly = Decimal(str(asset.monthly_depreciation))
            # 最后一个月取剩余余额，避免因舍入差异导致超出
            return min(monthly, remaining)

        if method == DepreciationMethod.ACCELERATED:
            # 双倍余额递减：读取当前账面净值（原值 - 累计折旧）
            book_value    = Decimal(str(asset.original_value)) - accumulated
            life_years    = asset.useful_life_months / 12
            monthly_rate  = Decimal(str(2.0 / life_years / 12))
            months_elapsed = asset.depreciation_months_elapsed
            months_left   = asset.useful_life_months - months_elapsed

            # 最后 24 个月切换为直线法
            if months_left <= 24:
                dep = (book_value - Decimal(str(asset.net_salvage_value))) / months_left
            else:
                dep = book_value * monthly_rate

            return min(dep.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), remaining)

        # 未知方法 fallback：直线
        return min(Decimal(str(asset.monthly_depreciation)), remaining)

    def _already_posted(self, asset: AssetRegister, period: str) -> bool:
        """
        检查该资产在该期间是否已有折旧凭证。
        通过凭证 memo 字段中的唯一标识判断（简单幂等保护）。
        """
        marker = f"[DEP:{asset.asset_id}:{period}]"
        exists = (
            self._db.query(VoucherHeader)
            .filter(VoucherHeader.memo.like(f"%{marker}%"))
            .first()
        )
        return exists is not None

    def _post_depreciation(
        self,
        asset:      AssetRegister,
        dep_amount: Decimal,
        period:     str,
        year:       int,
        month:      int,
        record_id:  int,
    ) -> VoucherHeader:
        """生成折旧凭证：借 管理费用，贷 累计折旧"""
        marker = f"[DEP:{asset.asset_id}:{period}]"
        memo   = f"{asset.asset_name} {period} 月折旧 {marker}"

        # 取期末最后一天作为凭证日期
        last_day = _last_day_of_month(year, month)

        header = VoucherHeader(
            record_id     = record_id,
            voucher_date  = last_day,
            total_amount  = dep_amount,
            memo          = memo,
            review_status = VoucherReviewStatus.POSTED,
        )
        self._db.add(header)
        self._db.flush()

        for code, direction in [
            (DEPRECIATION_EXPENSE_CODE, "DEBIT"),
            (ACCUMULATED_DEP_CODE,      "CREDIT"),
        ]:
            self._db.add(VoucherLine(
                voucher_id   = header.voucher_id,
                subject_code = code,
                direction    = direction,
                amount       = dep_amount,
                memo         = memo,
            ))
        return header

    def _update_asset(self, asset: AssetRegister, dep_amount: Decimal) -> None:
        """更新台账：累计折旧、已折月数、状态"""
        depreciable  = (
            Decimal(str(asset.original_value)) - Decimal(str(asset.net_salvage_value))
        )
        new_accum    = Decimal(str(asset.accumulated_depreciation)) + dep_amount
        asset.accumulated_depreciation   = new_accum
        asset.depreciation_months_elapsed = asset.depreciation_months_elapsed + 1

        if new_accum >= depreciable:
            asset.status = AssetStatus.FULLY_DEPRECIATED
            logger.info("Asset %s (%s) fully depreciated", asset.asset_id, asset.asset_name)

    def _assert_subjects_exist(self) -> None:
        for code in [DEPRECIATION_EXPENSE_CODE, ACCUMULATED_DEP_CODE]:
            if not self._db.query(AccountSubject).filter_by(subject_code=code).first():
                raise RuntimeError(
                    f"科目 {code} 不存在，请执行 dml.sql 初始化数据"
                )


def _last_day_of_month(year: int, month: int) -> date:
    """返回指定年月的最后一天。"""
    if month == 12:
        return date(year + 1, 1, 1).replace(day=1) - __import__('datetime').timedelta(days=1)
    return date(year, month + 1, 1) - __import__('datetime').timedelta(days=1)
