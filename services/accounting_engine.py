"""
AgentLedger — AccountingEngineService  (任务 3.2 + 3.3)

核心职责：
  1. 将 ExtractedRecord.expense_type（中文）映射到会计科目代码（查 account_subject 表）。
  2. 将 payer_name / counterparty 映射到 auxiliary_entity 行。
  3. 按业务场景组装借方 / 贷方明细。
  4. 强制校验  Σ借方 == Σ贷方（复式记账平衡）。
  5. 在事务中写入 voucher_header + voucher_line。

【科目映射规则（后端硬编码，不依赖 LLM）】
payment_method → 贷方（资金流出科目）
  员工垫付  → 2241 其他应付款（先挂账，后报销）
  现金      → 1001 库存现金
  银行转账  → 1002 银行存款
  微信支付  → 1012 其他货币资金
  支付宝    → 1012 其他货币资金
  未指定    → 1002 银行存款（默认）

expense_type → 借方（费用/资产科目）关键词映射表
  招待 / 餐 / 娱乐        → 6601 销售费用
  差旅 / 出差 / 交通 / 住宿 → 6602 管理费用
  办公 / 文具 / 打印       → 6602 管理费用
  工资 / 薪资 / 薪酬       → 6602 管理费用（应付职工薪酬走负债，见特殊分录）
  货款 / 原材料 / 采购      → 1403 原材料 / 2202 应付账款
  收款 / 销售              → 1002 银行存款（借）/ 6001 主营业务收入（贷）
"""
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from ai.json_parser import ExtractedRecord
from models.operational_record import OperationalRecord
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from models.account_subject import AccountSubject
from models.auxiliary_entity import AuxiliaryEntity

logger = logging.getLogger(__name__)


class AccountingError(ValueError):
    """Raised when a balanced entry cannot be constructed."""


# ── 支付方式 → 资金流出科目代码 ──────────────────────────────────────────────
PAYMENT_METHOD_CREDIT_MAP: dict[str, str] = {
    "员工垫付": "2241",   # 其他应付款
    "现金":     "1001",   # 库存现金
    "银行转账": "1002",   # 银行存款
    "微信支付": "1012",   # 其他货币资金
    "支付宝":   "1012",   # 其他货币资金
    "未指定":   "1002",   # 银行存款（默认）
}

# ── 费用类型关键词 → 借方科目代码 ────────────────────────────────────────────
EXPENSE_KEYWORD_DEBIT_MAP: list[tuple[list[str], str]] = [
    (["招待", "餐", "宴", "娱乐", "接待"],              "6601"),  # 销售费用
    (["差旅", "出差", "交通", "住宿", "机票", "高铁"],   "6602"),  # 管理费用
    (["办公", "文具", "打印", "耗材", "快递"],           "6602"),  # 管理费用
    (["工资", "薪资", "薪酬", "奖金", "绩效", "社保"],   "6602"),  # 管理费用（贷方走2211）
    (["广告", "推广", "营销", "促销"],                   "6601"),  # 销售费用
    (["货款", "采购", "原材料", "材料"],                 "1403"),  # 原材料
    (["水电", "物业", "租金", "房租", "物管"],           "6602"),  # 管理费用
    (["研发", "开发", "技术服务", "软件"],               "6604"),  # 研发费用
    (["利息", "手续费", "银行费", "汇兑"],               "6603"),  # 财务费用
    (["运费", "物流", "仓储", "配送"],                   "6601"),  # 销售费用
    (["维修", "维护", "保养", "修理"],                   "6602"),  # 管理费用
    (["保险", "车险", "意外险"],                         "6602"),  # 管理费用
    (["税", "附加税", "印花税", "房产税"],               "6403"),  # 税金及附加
    (["折旧", "摊销"],                                   "6602"),  # 管理费用
]

# 薪酬类关键词（贷方走 2211 应付职工薪酬，而非资金科目）
PAYROLL_KEYWORDS: list[str] = ["工资", "薪资", "薪酬", "奖金", "绩效", "社保", "公积金"]

# ── 收入类场景关键词（特殊：借资产 贷收入）───────────────────────────────────
INCOME_KEYWORDS: list[str] = ["收款", "销售", "回款", "到账", "收到"]


class AccountingEngineService:
    def __init__(self, db: Session) -> None:
        self._db = db

    # ── Public entry point ───────────────────────────────────────────────────

    def generate_voucher(
        self, record: OperationalRecord, extracted: ExtractedRecord
    ) -> VoucherHeader:
        """
        Build and persist a balanced double-entry voucher.
        Raises AccountingError if the entry cannot be balanced.
        """
        is_income = self._is_income(extracted.expense_type)

        if is_income:
            lines_spec = self._build_income_entry(extracted)
        else:
            lines_spec = self._build_expense_entry(extracted)

        self._assert_balanced(lines_spec)

        return self._persist_voucher(record, extracted, lines_spec)

    # ── Entry builders ───────────────────────────────────────────────────────

    def _build_expense_entry(
        self, ext: ExtractedRecord
    ) -> list[dict]:
        """
        费用类分录：
          借 费用科目          金额
          贷 支付科目          金额
        特殊：薪酬类分录贷方走 2211 应付职工薪酬
        """
        debit_code  = self._map_expense_to_debit(ext.expense_type)
        is_payroll  = self._is_payroll(ext.expense_type)
        credit_code = "2211" if is_payroll else self._map_payment_to_credit(ext.payment_method)

        entity_id = self._resolve_entity_id(ext.payer_name or ext.counterparty)

        return [
            {"direction": "DEBIT",  "subject_code": debit_code,
             "amount": ext.amount, "entity_id": entity_id,
             "memo": ext.memo},
            {"direction": "CREDIT", "subject_code": credit_code,
             "amount": ext.amount, "entity_id": entity_id,
             "memo": ext.memo},
        ]

    def _build_income_entry(
        self, ext: ExtractedRecord
    ) -> list[dict]:
        """
        收入类分录：
          借 银行存款 / 应收账款   金额
          贷 主营业务收入           金额
        """
        debit_code  = "1002"  # 银行存款
        credit_code = "6001"  # 主营业务收入
        entity_id   = self._resolve_entity_id(ext.counterparty)

        return [
            {"direction": "DEBIT",  "subject_code": debit_code,
             "amount": ext.amount, "entity_id": entity_id,
             "memo": ext.memo},
            {"direction": "CREDIT", "subject_code": credit_code,
             "amount": ext.amount, "entity_id": entity_id,
             "memo": ext.memo},
        ]

    # ── Mapping helpers ──────────────────────────────────────────────────────

    def _map_expense_to_debit(self, expense_type: str) -> str:
        for keywords, code in EXPENSE_KEYWORD_DEBIT_MAP:
            if any(kw in expense_type for kw in keywords):
                self._assert_subject_exists(code)
                return code
        # Default: 管理费用
        logger.warning("No keyword match for expense_type='%s', defaulting to 6602", expense_type)
        return "6602"

    def _map_payment_to_credit(self, payment_method: str) -> str:
        code = PAYMENT_METHOD_CREDIT_MAP.get(payment_method, "1002")
        self._assert_subject_exists(code)
        return code

    def _resolve_entity_id(self, name: str | None) -> int | None:
        if not name:
            return None
        entity = (
            self._db.query(AuxiliaryEntity)
            .filter(AuxiliaryEntity.entity_name == name,
                    AuxiliaryEntity.is_active == 1)
            .first()
        )
        if entity:
            return entity.entity_id
        # Auto-create unknown entity to avoid blocking the voucher
        new_entity = AuxiliaryEntity(entity_type="未分类", entity_name=name)
        self._db.add(new_entity)
        self._db.flush()
        logger.info("Auto-created auxiliary_entity: name=%s id=%s", name, new_entity.entity_id)
        return new_entity.entity_id

    def _assert_subject_exists(self, code: str) -> None:
        exists = self._db.query(AccountSubject).filter_by(subject_code=code).first()
        if not exists:
            raise AccountingError(
                f"Subject code '{code}' not found in account_subject table. "
                "Please run dml.sql to initialise master data."
            )

    # ── Balance check ────────────────────────────────────────────────────────

    @staticmethod
    def _assert_balanced(lines: list[dict]) -> None:
        total_debit  = sum(l["amount"] for l in lines if l["direction"] == "DEBIT")
        total_credit = sum(l["amount"] for l in lines if l["direction"] == "CREDIT")
        if total_debit != total_credit:
            raise AccountingError(
                f"Voucher is NOT balanced: debit={total_debit} credit={total_credit}"
            )

    @staticmethod
    def _is_income(expense_type: str) -> bool:
        return any(kw in expense_type for kw in INCOME_KEYWORDS)

    @staticmethod
    def _is_payroll(expense_type: str) -> bool:
        return any(kw in expense_type for kw in PAYROLL_KEYWORDS)

    # ── Persistence (inside caller's transaction) ────────────────────────────

    def _effective_voucher_date(self) -> date:
        """
        若今日所在期间已结账，返回下一个 OPEN 期间的第1天；否则返回今日。
        确保结账后新提交的流水不会落入已关闭的期间。
        """
        from models.accounting_period import AccountingPeriod, PeriodStatus
        today = date.today()
        period = (
            self._db.query(AccountingPeriod)
            .filter_by(year=today.year, month=today.month)
            .first()
        )
        if period and period.status == PeriodStatus.CLOSED:
            next_open = (
                self._db.query(AccountingPeriod)
                .filter(AccountingPeriod.status == PeriodStatus.OPEN)
                .order_by(AccountingPeriod.year, AccountingPeriod.month)
                .first()
            )
            if next_open:
                effective = date(next_open.year, next_open.month, 1)
                logger.info(
                    "Current period %d-%02d is CLOSED, using next open period: %s",
                    today.year, today.month, effective,
                )
                return effective
        return today

    def _persist_voucher(
        self,
        record: OperationalRecord,
        ext: ExtractedRecord,
        lines_spec: list[dict],
    ) -> VoucherHeader:
        header = VoucherHeader(
            record_id     = record.record_id,
            voucher_date  = self._effective_voucher_date(),
            total_amount  = ext.amount,
            memo          = ext.memo,
            review_status = VoucherReviewStatus.POSTED,
        )
        self._db.add(header)
        self._db.flush()   # get voucher_id

        for spec in lines_spec:
            line = VoucherLine(
                voucher_id          = header.voucher_id,
                subject_code        = spec["subject_code"],
                direction           = spec["direction"],
                amount              = spec["amount"],
                auxiliary_entity_id = spec.get("entity_id"),
                memo                = spec.get("memo"),
            )
            self._db.add(line)

        self._db.flush()
        logger.info(
            "Voucher id=%s created: %d lines, amount=%s",
            header.voucher_id, len(lines_spec), ext.amount,
        )

        # 审计日志：自动生成并入账的凭证
        from services.audit_guard import write_audit_log
        write_audit_log(
            self._db, "voucher_header", header.voucher_id,
            action      = "CREATE",
            description = f"自动记账凭证生成并入账：{ext.memo}",
            after_value = {"review_status": "POSTED", "amount": str(ext.amount)},
            username    = "system_auto",
        )
        return header
