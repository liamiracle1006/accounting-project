"""
AgentLedger V4.0 — PeriodClosingService (Sprint 3.3)

月末/年末结账引擎（三模块）：

模块一：transfer_pnl()
  - 扫描当期所有 6xxx 损益科目（企业会计准则）净发生额
  - 生成系统结转凭证（直接构造 ORM，状态直接设为 POSTED）
  - 12月额外：将全年 4103 本年利润清零，结转至 4104 利润分配-未分配利润
  - 幂等防重：若 closing_voucher_id 已存在则先软删除再重算
  - 不自动 commit，事务由路由层控制

模块二：close_period()
  守门员三道防线：
  1. 断号自动修复（静默调用 reorganize）
  2. 未审核凭证拦截（DRAFT / PENDING_REVIEW → 400）
  3. 损益未结平拦截（6xxx 期末不为零 → 400）
  4. 全量试算平衡兜底（借贷不平 → 500）
  通过后：status=CLOSED，自动创建下期 OPEN

模块三：unclose_period()
  - 仅允许最后一个 CLOSED 期间反结账
  - 软删除 closing_voucher_id 对应凭证
  - 删除下期空白 period 记录（若无凭证）
  - status 回退为 OPEN

多租户：所有方法均通过 tenant_id + account_set_id 严格隔离
"""
import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from models.accounting_period import AccountingPeriod, PeriodStatus
from models.operational_record import OperationalRecord, RecordStatus
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine

logger = logging.getLogger(__name__)

# ── 损益科目硬编码（企业会计准则 6xxx）────────────────────────────────────────
# (code_prefix, normal_balance_direction)
INCOME_ACCOUNTS: list[tuple[str, str]] = [
    ("6001", "CREDIT"),   # 主营业务收入
    ("6051", "CREDIT"),   # 其他业务收入
    ("6101", "CREDIT"),   # 公允价值变动收益
    ("6111", "CREDIT"),   # 投资收益
    ("6117", "CREDIT"),   # 其他收益
    ("6301", "CREDIT"),   # 营业外收入
]
EXPENSE_ACCOUNTS: list[tuple[str, str]] = [
    ("6401", "DEBIT"),    # 主营业务成本
    ("6402", "DEBIT"),    # 其他业务成本
    ("6403", "DEBIT"),    # 税金及附加
    ("6601", "DEBIT"),    # 销售费用
    ("6602", "DEBIT"),    # 管理费用
    ("6603", "DEBIT"),    # 财务费用
    ("6604", "DEBIT"),    # 研发费用
    ("6701", "DEBIT"),    # 资产减值损失
    ("6711", "DEBIT"),    # 营业外支出
    ("6801", "DEBIT"),    # 所得税费用
]

NET_PROFIT_CODE        = "4103"   # 本年利润
RETAINED_EARNINGS_CODE = "4104"   # 利润分配-未分配利润


# ── 返回值 Dataclass ──────────────────────────────────────────────────────────

@dataclass
class TransferPnLResult:
    year:       int
    month:      int
    net_profit: Decimal
    voucher_id: int
    message:    str


@dataclass
class CloseResult:
    year:              int
    month:             int
    reorganized_count: int
    next_period_year:  int
    next_period_month: int
    message:           str


@dataclass
class UncloseResult:
    year:    int
    month:   int
    message: str


# ── 自定义异常 ────────────────────────────────────────────────────────────────

class PeriodNotFoundError(Exception):
    pass

class PeriodClosingError(Exception):
    pass

class PeriodAlreadyClosedError(PeriodClosingError):
    pass

class PeriodNotClosedError(PeriodClosingError):
    pass


# ════════════════════════════════════════════════════════════════════════════
# PeriodClosingService
# ════════════════════════════════════════════════════════════════════════════

class PeriodClosingService:

    def __init__(self, db: Session) -> None:
        self._db = db

    # ══════════════════════════════════════════════════════════════════════════
    # 公共辅助：期间管理
    # ══════════════════════════════════════════════════════════════════════════

    def get_or_create_period(
        self,
        year: int, month: int,
        tenant_id: int, account_set_id: int,
    ) -> AccountingPeriod:
        p = (
            self._db.query(AccountingPeriod)
            .filter_by(
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                year           = year,
                month          = month,
            )
            .first()
        )
        if not p:
            p = AccountingPeriod(
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                year           = year,
                month          = month,
                status         = PeriodStatus.OPEN,
            )
            self._db.add(p)
            self._db.flush()
        return p

    def list_periods(
        self,
        tenant_id: int, account_set_id: int,
        limit: int = 24,
    ) -> list[AccountingPeriod]:
        return (
            self._db.query(AccountingPeriod)
            .filter_by(tenant_id=tenant_id, account_set_id=account_set_id)
            .order_by(AccountingPeriod.year.desc(), AccountingPeriod.month.desc())
            .limit(limit)
            .all()
        )

    def get_period(
        self,
        year: int, month: int,
        tenant_id: int, account_set_id: int,
    ) -> AccountingPeriod:
        p = (
            self._db.query(AccountingPeriod)
            .filter_by(
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                year           = year,
                month          = month,
            )
            .first()
        )
        if p is None:
            raise PeriodNotFoundError(f"期间 {year}-{month:02d} 不存在")
        return p

    # ══════════════════════════════════════════════════════════════════════════
    # 模块一：结转本期损益
    # ══════════════════════════════════════════════════════════════════════════

    def transfer_pnl(
        self,
        tenant_id: int, account_set_id: int,
        year: int, month: int,
        creator_id: int | None = None,
    ) -> TransferPnLResult:
        """
        结转本期损益（幂等：重复调用先删旧凭证再重算）。

        生成逻辑：
          1. 汇总当期所有 INCOME_ACCOUNTS（贷方余额）→ 借方冲销
          2. 汇总当期所有 EXPENSE_ACCOUNTS（借方余额）→ 贷方冲销
          3. 轧差净利润 → 4103 本年利润（盈利记贷，亏损记借）
          4. 若 month == 12：额外追加全年 4103 余额 → 4104（年结清零）

        返回值中不包含 commit，由路由层负责提交事务。
        """
        period    = self.get_or_create_period(year, month, tenant_id, account_set_id)
        date_from = date(year, month, 1)
        date_to   = self._last_day(year, month)

        # ── 幂等防重：软删除已有的结转凭证 ──────────────────────────────────
        if period.closing_voucher_id is not None:
            old_vh = self._db.get(VoucherHeader, period.closing_voucher_id)
            if old_vh is not None and not old_vh.is_deleted:
                old_vh.is_deleted = True
                logger.info(
                    "transfer_pnl 防重：软删除旧结转凭证 voucher_id=%d，重新生成",
                    period.closing_voucher_id,
                )
            period.closing_voucher_id = None
            self._db.flush()

        # ── 计算各损益科目净发生额 ───────────────────────────────────────────
        income_lines: list[dict] = []
        for prefix, _ in INCOME_ACCOUNTS:
            amt = self._sum_period(prefix, "CREDIT", tenant_id, account_set_id, date_from, date_to)
            if amt > 0:
                income_lines.append({"subject_code": prefix, "direction": "DEBIT", "amount": amt})

        expense_lines: list[dict] = []
        for prefix, _ in EXPENSE_ACCOUNTS:
            amt = self._sum_period(prefix, "DEBIT", tenant_id, account_set_id, date_from, date_to)
            if amt > 0:
                expense_lines.append({"subject_code": prefix, "direction": "CREDIT", "amount": amt})

        income_total  = sum(l["amount"] for l in income_lines)
        expense_total = sum(l["amount"] for l in expense_lines)
        net_profit    = income_total - expense_total

        if income_total == 0 and expense_total == 0:
            raise PeriodClosingError(
                f"{year}-{month:02d} 期间无损益数据（收入和费用均为 0），无需结转"
            )

        # ── 组装分录行 ────────────────────────────────────────────────────────
        lines: list[dict] = []
        lines.extend(income_lines)    # 借：收入科目归零
        lines.extend(expense_lines)   # 贷：费用/成本科目归零

        # 轧差净利润 → 4103 本年利润
        if net_profit > 0:
            lines.append({"subject_code": NET_PROFIT_CODE, "direction": "CREDIT", "amount": net_profit})
        elif net_profit < 0:
            lines.append({"subject_code": NET_PROFIT_CODE, "direction": "DEBIT",  "amount": abs(net_profit)})
        # net_profit == 0：收支相等，无需 4103 分录，但仍需生成凭证归零各科目

        # ── 12月年结：4103 全年余额 → 4104 ───────────────────────────────────
        if month == 12:
            year_start  = date(year, 1, 1)
            year_end    = date(year, 12, 31)
            # 全年 4103 净余额（含本次结转的贡献）
            # 本次结转后 4103 = 历史累计余额 + 本月净利润
            hist_4103 = self._sum_4103_balance(tenant_id, account_set_id, year_start, date_to)
            total_4103 = hist_4103 + net_profit

            if total_4103 != 0:
                if total_4103 > 0:
                    # 全年盈利：借 4103 / 贷 4104
                    lines.append({"subject_code": NET_PROFIT_CODE,        "direction": "DEBIT",  "amount": total_4103})
                    lines.append({"subject_code": RETAINED_EARNINGS_CODE, "direction": "CREDIT", "amount": total_4103})
                else:
                    # 全年亏损：贷 4103（减少其借方余额）/ 借 4104
                    lines.append({"subject_code": NET_PROFIT_CODE,        "direction": "CREDIT", "amount": abs(total_4103)})
                    lines.append({"subject_code": RETAINED_EARNINGS_CODE, "direction": "DEBIT",  "amount": abs(total_4103)})
                logger.info(
                    "年结：4103 全年余额 %s 结转至 4104", total_4103
                )

        # ── 持久化结转凭证 ────────────────────────────────────────────────────
        memo = f"{year}-{month:02d} 结转本期损益"
        if month == 12:
            memo = f"{year} 年结：结转本期损益及年末利润"

        closing_rec = OperationalRecord(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            raw_text       = f"[系统自动] {memo}",
            status         = RecordStatus.PROCESSED,
        )
        self._db.add(closing_rec)
        self._db.flush()

        total_debit = sum(
            l["amount"] for l in lines if l["direction"] == "DEBIT"
        )
        closing_vh = VoucherHeader(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            record_id      = closing_rec.record_id,
            voucher_date   = date_to,
            voucher_word   = "转",
            total_amount   = total_debit,
            memo           = memo,
            review_status  = VoucherReviewStatus.POSTED,
            creator_id     = creator_id,
            is_deleted     = False,
        )
        self._db.add(closing_vh)
        self._db.flush()

        for spec in lines:
            self._db.add(VoucherLine(
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                voucher_id     = closing_vh.voucher_id,
                subject_code   = spec["subject_code"],
                direction      = spec["direction"],
                amount         = Decimal(str(spec["amount"])),
                memo           = memo,
            ))

        # 更新期间的 closing_voucher_id（但 status 仍为 OPEN）
        period.closing_voucher_id = closing_vh.voucher_id

        logger.info(
            "transfer_pnl 完成：%d-%02d net_profit=%s voucher_id=%d",
            year, month, net_profit, closing_vh.voucher_id,
        )
        return TransferPnLResult(
            year       = year,
            month      = month,
            net_profit = net_profit,
            voucher_id = closing_vh.voucher_id,
            message    = f"{year}-{month:02d} 损益结转完成，净利润 ¥{net_profit:,.2f}",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 模块二：守门员结账
    # ══════════════════════════════════════════════════════════════════════════

    def close_period(
        self,
        tenant_id: int, account_set_id: int,
        year: int, month: int,
        user_id: int,
    ) -> CloseResult:
        """
        执行月末结账，严格三道防线。

        防线一：断号自动修复（静默 reorganize）
        防线二：未审核凭证拦截（DRAFT/PENDING_REVIEW → 400）
        防线三：损益未结平拦截（6xxx 期末不为零 → 400）
        防线四：全量试算平衡兜底（借 ≠ 贷 → 500）

        通过后：status=CLOSED，自动创建下期 OPEN。
        不调用 db.commit()，事务由路由层控制。
        """
        period = self.get_or_create_period(year, month, tenant_id, account_set_id)

        if period.status == PeriodStatus.CLOSED:
            raise PeriodAlreadyClosedError(f"{year}-{month:02d} 已结账，无法重复操作")

        date_from = date(year, month, 1)
        date_to   = self._last_day(year, month)

        # ── 防线一：断号自动修复 ──────────────────────────────────────────────
        from services.voucher_service import VoucherService
        from schemas.voucher_schemas import ReorganizeInput
        vs = VoucherService(self._db)
        reorganize_result = vs.reorganize(
            tenant_id, account_set_id,
            ReorganizeInput(period_year=year, period_month=month),
        )
        reorganized_count = reorganize_result.updated_count
        logger.info("断号整理：期间 %d-%02d 共 %d 条凭证", year, month, reorganized_count)

        # ── 防线二：未审核凭证拦截 ────────────────────────────────────────────
        draft_count = (
            self._db.query(func.count(VoucherHeader.voucher_id))
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherHeader.is_deleted     == False,
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status.in_([
                    VoucherReviewStatus.DRAFT,
                    VoucherReviewStatus.PENDING_REVIEW,
                ]),
            )
            .scalar()
        )
        if draft_count > 0:
            raise PeriodClosingError(
                f"期间 {year}-{month:02d} 存在 {draft_count} 张未审核凭证（DRAFT/PENDING_REVIEW），"
                "请全部审核后再执行结账"
            )

        # ── 防线三：损益未结平拦截 ────────────────────────────────────────────
        residual_income  = sum(
            self._sum_period(p, "CREDIT", tenant_id, account_set_id, date_from, date_to)
            for p, _ in INCOME_ACCOUNTS
        )
        residual_expense = sum(
            self._sum_period(p, "DEBIT",  tenant_id, account_set_id, date_from, date_to)
            for p, _ in EXPENSE_ACCOUNTS
        )
        if abs(residual_income) > Decimal("0.01") or abs(residual_expense) > Decimal("0.01"):
            raise PeriodClosingError(
                f"当期损益未结平（收入余额 {residual_income:.2f}，费用余额 {residual_expense:.2f}），"
                "请先执行【结转本期损益】"
            )

        # ── 防线四：全量试算平衡兜底 ──────────────────────────────────────────
        self._assert_trial_balance(tenant_id, account_set_id, date_from, date_to)

        # ── 结账 ─────────────────────────────────────────────────────────────
        period.status    = PeriodStatus.CLOSED
        period.closed_at = datetime.now(timezone.utc)
        period.closed_by = user_id

        # 审计日志
        from services.audit_guard import audit_period_closed
        audit_period_closed(self._db, f"{year}-{month:02d}")

        # 自动创建下期 OPEN
        ny, nm = (year, month + 1) if month < 12 else (year + 1, 1)
        self.get_or_create_period(ny, nm, tenant_id, account_set_id)

        logger.info("期间 %d-%02d 结账完成，下期 %d-%02d 已创建", year, month, ny, nm)
        return CloseResult(
            year              = year,
            month             = month,
            reorganized_count = reorganized_count,
            next_period_year  = ny,
            next_period_month = nm,
            message           = f"{year}-{month:02d} 结账完成，下期 {ny}-{nm:02d} 已开启",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 模块三：反结账
    # ══════════════════════════════════════════════════════════════════════════

    def unclose_period(
        self,
        tenant_id: int, account_set_id: int,
        year: int, month: int,
    ) -> UncloseResult:
        """
        反结账：仅允许最后一个 CLOSED 期间回退为 OPEN。

        操作：
          1. 验证是最后一个 CLOSED 期间
          2. 软删除 closing_voucher_id 对应凭证（结转凭证）
          3. 将期间状态回退为 OPEN，清空结账字段
          4. 若下期 period 存在且无凭证，则物理删除该空白期间记录
        """
        period = self.get_period(year, month, tenant_id, account_set_id)

        if period.status != PeriodStatus.CLOSED:
            raise PeriodNotClosedError(f"{year}-{month:02d} 并非已结账状态")

        # 验证是最后一个 CLOSED 期间
        later_closed = (
            self._db.query(func.count(AccountingPeriod.period_id))
            .filter(
                AccountingPeriod.tenant_id      == tenant_id,
                AccountingPeriod.account_set_id == account_set_id,
                AccountingPeriod.status         == PeriodStatus.CLOSED,
                (AccountingPeriod.year * 100 + AccountingPeriod.month)
                > (year * 100 + month),
            )
            .scalar()
        )
        if later_closed > 0:
            raise PeriodClosingError(
                f"期间 {year}-{month:02d} 不是最后一个已结账期间，"
                "只允许对最近的已结账期间执行反结账操作"
            )

        # 软删除结转凭证
        if period.closing_voucher_id is not None:
            old_vh = self._db.get(VoucherHeader, period.closing_voucher_id)
            if old_vh is not None and not old_vh.is_deleted:
                old_vh.is_deleted = True
                logger.info(
                    "反结账：软删除结转凭证 voucher_id=%d", period.closing_voucher_id
                )

        # 回退期间状态
        period.status             = PeriodStatus.OPEN
        period.closed_at          = None
        period.closed_by          = None
        period.closing_voucher_id = None

        # 删除下期空白 period 记录
        ny, nm = (year, month + 1) if month < 12 else (year + 1, 1)
        next_period = (
            self._db.query(AccountingPeriod)
            .filter_by(
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                year           = ny,
                month          = nm,
            )
            .first()
        )
        if next_period is not None:
            next_has_vouchers = (
                self._db.query(func.count(VoucherHeader.voucher_id))
                .filter(
                    VoucherHeader.tenant_id      == tenant_id,
                    VoucherHeader.account_set_id == account_set_id,
                    VoucherHeader.is_deleted     == False,
                    VoucherHeader.voucher_date   >= date(ny, nm, 1),
                    VoucherHeader.voucher_date   <= self._last_day(ny, nm),
                )
                .scalar()
            )
            if next_has_vouchers == 0:
                self._db.delete(next_period)
                logger.info("反结账：删除空白下期 %d-%02d", ny, nm)

        logger.info("期间 %d-%02d 反结账完成", year, month)
        return UncloseResult(
            year    = year,
            month   = month,
            message = f"{year}-{month:02d} 反结账完成，期间已重新开启",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 私有辅助方法
    # ══════════════════════════════════════════════════════════════════════════

    def _sum_period(
        self,
        code_prefix: str,
        direction: str,
        tenant_id: int,
        account_set_id: int,
        date_from: date,
        date_to: date,
    ) -> Decimal:
        """汇总指定科目前缀、方向、期间内的 POSTED 凭证金额（不含软删除）。"""
        row = (
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherLine.subject_code.like(f"{code_prefix}%"),
                VoucherLine.direction        == direction,
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status  == VoucherReviewStatus.POSTED,
                VoucherHeader.is_deleted     == False,
            )
            .scalar()
        )
        return Decimal(str(row or 0))

    def _sum_4103_balance(
        self,
        tenant_id: int,
        account_set_id: int,
        date_from: date,
        date_to: date,
    ) -> Decimal:
        """
        计算 4103 本年利润的净余额（贷方合计 - 借方合计）。
        用于 12月年结前获取历史累计值（不含本月结转贡献）。
        """
        credit = self._sum_period("4103", "CREDIT", tenant_id, account_set_id, date_from, date_to)
        debit  = self._sum_period("4103", "DEBIT",  tenant_id, account_set_id, date_from, date_to)
        return credit - debit

    def _assert_trial_balance(
        self,
        tenant_id: int,
        account_set_id: int,
        date_from: date,
        date_to: date,
    ) -> None:
        """
        全量试算平衡兜底：当期 POSTED 凭证借方合计 == 贷方合计。
        差额 > 0.01 则抛 500 异常。
        """
        total_debit = (
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherLine.direction        == "DEBIT",
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status  == VoucherReviewStatus.POSTED,
                VoucherHeader.is_deleted     == False,
            )
            .scalar()
        )
        total_credit = (
            self._db.query(func.sum(VoucherLine.amount))
            .join(VoucherHeader, VoucherLine.voucher_id == VoucherHeader.voucher_id)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherLine.direction        == "CREDIT",
                VoucherHeader.voucher_date   >= date_from,
                VoucherHeader.voucher_date   <= date_to,
                VoucherHeader.review_status  == VoucherReviewStatus.POSTED,
                VoucherHeader.is_deleted     == False,
            )
            .scalar()
        )
        debit  = Decimal(str(total_debit  or 0))
        credit = Decimal(str(total_credit or 0))
        if abs(debit - credit) > Decimal("0.01"):
            raise RuntimeError(
                f"[系统告警] 试算平衡异常：当期借方合计 {debit:.2f} ≠ 贷方合计 {credit:.2f}，"
                "请检查底层数据，禁止结账"
            )

    @staticmethod
    def _last_day(year: int, month: int) -> date:
        return date(year, month, calendar.monthrange(year, month)[1])
