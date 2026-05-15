"""
AgentLedger V4.0 — VoucherService (Sprint 3.2)

职责：
  凭证（VoucherHeader + VoucherLine）的完整生命周期管理：
    - 手工新建 / 查询（带分页 + 多维过滤）/ 更新 / 软删除 / 还原
    - 状态机：DRAFT → PENDING_REVIEW → POSTED / REJECTED，以及 POSTED → PENDING_REVIEW（反审核）
    - 断号整理：按会计期间对所有未删除凭证重新顺序编号
    - 确认入账：将 AI 凭证草稿（ConfirmVoucherInput）持久化到数据库

状态流转（与 AuditGuard 配合）：
  DRAFT           — 草稿，可编辑、可软删除
  PENDING_REVIEW  — 已提交，不可编辑，等待审核人操作
  POSTED          — 已过账，AuditGuard 防篡改（允许反审核降为 PENDING_REVIEW）
  REJECTED        — 驳回，可重新编辑后再提交

异常体系：
  VoucherNotFoundError  — 404（凭证不存在或不属于当前账套）
  VoucherLockedError    — 403（POSTED 凭证禁止修改/删除）
  VoucherStateError     — 422（非法状态流转，如从 PENDING_REVIEW 直接审核再次提交）
"""
import logging
from datetime import datetime, date as date_type
from decimal import Decimal

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from models.auxiliary_entity import AuxiliaryEntity
from models.operational_record import OperationalRecord, RecordStatus
from models.voucher_header import VoucherHeader, VoucherReviewStatus
from models.voucher_line import VoucherLine
from schemas.voucher_schemas import (
    VoucherCreateInput,
    VoucherListItem,
    VoucherOut,
    VoucherQuery,
    PaginatedVouchers,
    ReorganizeInput,
    ReorganizeResult,
    VoucherUpdateInput,
)
from schemas.voucher_ai_schemas import ConfirmVoucherInput

logger = logging.getLogger(__name__)

# key → AuxiliaryEntity.entity_type 映射（白名单）
_AUX_TYPE_MAP = {
    "customer":  "CUSTOMER",
    "supplier":  "SUPPLIER",
    "employee":  "EMPLOYEE",
    "project":   "PROJECT",
    "dept":      "DEPT",
}


# ── 自定义异常 ────────────────────────────────────────────────────────────────

class VoucherNotFoundError(Exception):
    pass

class VoucherLockedError(Exception):
    """POSTED 凭证禁止修改或删除。"""
    pass

class VoucherStateError(Exception):
    """非法状态流转。"""
    pass


# ── 序列化辅助 ────────────────────────────────────────────────────────────────

def _fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, str):
        return d
    return d.strftime("%Y-%m-%d")


def _fmt_dt(dt) -> str:
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _serialize_line(line: VoucherLine) -> dict:
    return {
        "line_id":             line.line_id,
        "subject_code":        line.subject_code,
        "direction":           line.direction,
        "amount":              float(line.amount),
        "memo":                line.memo,
        "auxiliary_entity_id": line.auxiliary_entity_id,
    }


def _serialize_header(header: VoucherHeader, include_lines: bool = True) -> dict:
    base = {
        "voucher_id":     header.voucher_id,
        "voucher_number": header.voucher_number,
        "voucher_word":   header.voucher_word,
        "voucher_date":   _fmt_date(header.voucher_date),
        "memo":           header.memo,
        "total_amount":   float(header.total_amount),
        "review_status":  header.review_status,
        "creator_id":     header.creator_id,
        "reviewer_id":    header.reviewer_id,
        "review_note":    header.review_note,
        "reviewed_at":    _fmt_dt(header.reviewed_at),
        "is_deleted":     header.is_deleted,
        "created_at":     _fmt_dt(header.created_at),
    }
    if include_lines:
        base["lines"] = [_serialize_line(l) for l in header.lines]
        return VoucherOut(**base)
    else:
        base["line_count"] = len(header.lines)
        return VoucherListItem(**base)


# ════════════════════════════════════════════════════════════════════════════
# VoucherService
# ════════════════════════════════════════════════════════════════════════════

class VoucherService:

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── 私有：按 ID 取凭证，做租户隔离 ──────────────────────────────────────

    def _get_or_404(self, voucher_id: int, tenant_id: int, account_set_id: int) -> VoucherHeader:
        vh = (
            self._db.query(VoucherHeader)
            .filter(
                VoucherHeader.voucher_id    == voucher_id,
                VoucherHeader.tenant_id     == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
            )
            .first()
        )
        if vh is None:
            raise VoucherNotFoundError(f"凭证 {voucher_id} 不存在或无权访问")
        return vh

    # ── 私有：期间结账锁（CLOSED 期间禁止所有写操作）────────────────────────

    def _check_period_open(
        self,
        voucher_date,
        tenant_id: int,
        account_set_id: int,
    ) -> None:
        """
        校验凭证日期所属期间的状态。
        若 status == CLOSED，抛出 VoucherLockedError（HTTP 403）。
        若期间不存在，默认允许（尚未建期间的账套不受限）。
        """
        from models.accounting_period import AccountingPeriod, PeriodStatus
        year  = voucher_date.year
        month = voucher_date.month
        period = (
            self._db.query(AccountingPeriod)
            .filter_by(
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                year           = year,
                month          = month,
            )
            .first()
        )
        if period is not None and period.status == PeriodStatus.CLOSED:
            raise VoucherLockedError(
                f"期间 {year}-{month:02d} 已结账(CLOSED)，禁止新增或修改凭证。"
                "如需修改，请先通过【反结账】接口重新开启该期间。"
            )

    # ── 私有：POSTED 写保护检查 ──────────────────────────────────────────────

    @staticmethod
    def _check_editable(vh: VoucherHeader) -> None:
        if vh.review_status == VoucherReviewStatus.POSTED:
            raise VoucherLockedError(
                f"凭证 {vh.voucher_id} 已过账(POSTED)，禁止修改或删除。"
                "如需反审核，请先通过「反审核」接口将状态回退至 PENDING_REVIEW。"
            )

    # ── 私有：辅助核算数据转 entity_id（查找或自动创建）──────────────────────

    def _resolve_auxiliary(
        self,
        auxiliary_data: dict | None,
        tenant_id: int,
        account_set_id: int,
    ) -> int | None:
        if not auxiliary_data:
            return None
        for key, name in auxiliary_data.items():
            entity_type = _AUX_TYPE_MAP.get(key)
            if not entity_type or not name:
                continue
            entity = (
                self._db.query(AuxiliaryEntity)
                .filter(
                    AuxiliaryEntity.tenant_id      == tenant_id,
                    AuxiliaryEntity.account_set_id == account_set_id,
                    AuxiliaryEntity.entity_type    == entity_type,
                    AuxiliaryEntity.entity_name    == str(name),
                )
                .first()
            )
            if entity is None:
                entity = AuxiliaryEntity(
                    tenant_id      = tenant_id,
                    account_set_id = account_set_id,
                    entity_type    = entity_type,
                    entity_name    = str(name),
                )
                self._db.add(entity)
                self._db.flush()   # 获取 entity_id，不单独 commit
            return entity.entity_id
        return None

    # ── 私有：创建 OperationalRecord 以满足 record_id FK ─────────────────────

    def _create_operational_record(
        self,
        raw_text: str,
        tenant_id: int,
        account_set_id: int,
    ) -> OperationalRecord:
        rec = OperationalRecord(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            raw_text       = raw_text,
            status         = RecordStatus.PROCESSED,
        )
        self._db.add(rec)
        self._db.flush()   # 获取 record_id
        return rec

    # ── 私有：从行列表构建 VoucherLine ORM 对象 ──────────────────────────────

    def _build_lines(
        self,
        lines_in,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
        has_auxiliary_data: bool = False,
    ) -> list[VoucherLine]:
        result = []
        for li in lines_in:
            if has_auxiliary_data:
                aux_id = self._resolve_auxiliary(
                    getattr(li, "auxiliary_data", None),
                    tenant_id, account_set_id,
                )
            else:
                aux_id = getattr(li, "auxiliary_entity_id", None)

            vl = VoucherLine(
                tenant_id           = tenant_id,
                account_set_id      = account_set_id,
                voucher_id          = voucher_id,
                subject_code        = li.subject_code,
                direction           = li.direction,
                amount              = Decimal(str(li.amount)),
                memo                = li.memo,
                auxiliary_entity_id = aux_id,
            )
            result.append(vl)
        return result

    # ══════════════════════════════════════════════════════════════════════════
    # 1. 查询列表（分页 + 多维过滤）
    # ══════════════════════════════════════════════════════════════════════════

    def get_voucher_list(
        self,
        tenant_id: int,
        account_set_id: int,
        q: VoucherQuery,
    ) -> PaginatedVouchers:
        query = (
            self._db.query(VoucherHeader)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
            )
        )

        # 软删除过滤（默认排除）
        if not q.include_deleted:
            query = query.filter(VoucherHeader.is_deleted == False)

        # 会计期间（year + month 从 voucher_date 提取）
        if q.period_year is not None:
            query = query.filter(
                extract("year", VoucherHeader.voucher_date) == q.period_year
            )
        if q.period_month is not None:
            query = query.filter(
                extract("month", VoucherHeader.voucher_date) == q.period_month
            )

        # 审核状态过滤（DRAFT / PENDING_REVIEW / POSTED / REJECTED）
        if q.review_status:
            query = query.filter(VoucherHeader.review_status == q.review_status.upper())

        # 凭证字精确匹配
        if q.voucher_word:
            query = query.filter(VoucherHeader.voucher_word == q.voucher_word)

        # 摘要模糊搜索
        if q.summary_keyword:
            query = query.filter(
                VoucherHeader.memo.ilike(f"%{q.summary_keyword}%")
            )

        # 科目编码前缀匹配（JOIN VoucherLine，DISTINCT 避免重复行）
        if q.subject_code:
            query = (
                query
                .join(VoucherLine, VoucherLine.voucher_id == VoucherHeader.voucher_id)
                .filter(VoucherLine.subject_code.like(f"{q.subject_code}%"))
                .distinct()
            )

        # 金额区间（对 total_amount 过滤）
        if q.min_amount is not None:
            query = query.filter(VoucherHeader.total_amount >= q.min_amount)
        if q.max_amount is not None:
            query = query.filter(VoucherHeader.total_amount <= q.max_amount)

        total = query.count()

        # 排序：日期倒序，同日按凭证号升序
        query = query.order_by(
            VoucherHeader.voucher_date.desc(),
            VoucherHeader.voucher_number.asc(),
            VoucherHeader.voucher_id.asc(),
        )

        offset = (q.page - 1) * q.page_size
        rows = query.offset(offset).limit(q.page_size).all()

        return PaginatedVouchers(
            total     = total,
            page      = q.page,
            page_size = q.page_size,
            items     = [_serialize_header(r, include_lines=False) for r in rows],
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 2. 查询单条凭证（含分录行）
    # ══════════════════════════════════════════════════════════════════════════

    def get_voucher(
        self,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
    ) -> VoucherOut:
        vh = self._get_or_404(voucher_id, tenant_id, account_set_id)
        return _serialize_header(vh, include_lines=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 3. 手工新建凭证
    # ══════════════════════════════════════════════════════════════════════════

    def create_voucher(
        self,
        tenant_id: int,
        account_set_id: int,
        body: VoucherCreateInput,
        creator_id: int | None = None,
    ) -> VoucherHeader:
        self._check_period_open(body.voucher_date, tenant_id, account_set_id)
        rec = self._create_operational_record(
            body.memo or "手工凭证", tenant_id, account_set_id
        )
        total = Decimal(str(sum(l.amount for l in body.lines if l.direction == "DEBIT")))
        vh = VoucherHeader(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            record_id      = rec.record_id,
            voucher_date   = body.voucher_date,
            voucher_word   = body.voucher_word,
            total_amount   = total,
            memo           = body.memo,
            creator_id     = creator_id,
            review_status  = VoucherReviewStatus.DRAFT,
            is_deleted     = False,
        )
        self._db.add(vh)
        self._db.flush()

        lines = self._build_lines(body.lines, vh.voucher_id, tenant_id, account_set_id)
        self._db.add_all(lines)
        return vh

    # ══════════════════════════════════════════════════════════════════════════
    # 4. 更新凭证（POSTED 凭证拒绝）
    # ══════════════════════════════════════════════════════════════════════════

    def update_voucher(
        self,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
        body: VoucherUpdateInput,
    ) -> VoucherHeader:
        vh = self._get_or_404(voucher_id, tenant_id, account_set_id)
        self._check_period_open(vh.voucher_date, tenant_id, account_set_id)
        self._check_editable(vh)

        if vh.is_deleted:
            raise ValueError(f"凭证 {voucher_id} 已软删除，请先还原后再修改")

        if body.voucher_date is not None:
            vh.voucher_date = body.voucher_date
        if body.voucher_word is not None:
            vh.voucher_word = body.voucher_word
        if body.memo is not None:
            vh.memo = body.memo

        if body.lines is not None:
            # 完整替换行：先删旧行，再批量插入新行
            for old_line in list(vh.lines):
                self._db.delete(old_line)
            self._db.flush()

            new_lines = self._build_lines(body.lines, vh.voucher_id, tenant_id, account_set_id)
            self._db.add_all(new_lines)
            vh.total_amount = Decimal(
                str(sum(l.amount for l in body.lines if l.direction == "DEBIT"))
            )

        return vh

    # ══════════════════════════════════════════════════════════════════════════
    # 5. 软删除（仅 DRAFT 状态）
    # ══════════════════════════════════════════════════════════════════════════

    def soft_delete(
        self,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
    ) -> VoucherHeader:
        vh = self._get_or_404(voucher_id, tenant_id, account_set_id)
        self._check_period_open(vh.voucher_date, tenant_id, account_set_id)
        self._check_editable(vh)   # POSTED → 403

        if vh.review_status == VoucherReviewStatus.PENDING_REVIEW:
            raise VoucherStateError(
                f"凭证 {voucher_id} 处于待审核状态，请先反审核后再删除"
            )
        if vh.is_deleted:
            raise ValueError(f"凭证 {voucher_id} 已在回收站中")

        vh.is_deleted = True
        return vh

    # ══════════════════════════════════════════════════════════════════════════
    # 6. 回收站列表
    # ══════════════════════════════════════════════════════════════════════════

    def list_trash(
        self,
        tenant_id: int,
        account_set_id: int,
    ) -> list[VoucherListItem]:
        rows = (
            self._db.query(VoucherHeader)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherHeader.is_deleted     == True,
            )
            .order_by(VoucherHeader.voucher_date.desc())
            .all()
        )
        return [_serialize_header(r, include_lines=False) for r in rows]

    # ══════════════════════════════════════════════════════════════════════════
    # 7. 还原（从回收站恢复）
    # ══════════════════════════════════════════════════════════════════════════

    def restore(
        self,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
    ) -> VoucherHeader:
        vh = self._get_or_404(voucher_id, tenant_id, account_set_id)
        if not vh.is_deleted:
            raise ValueError(f"凭证 {voucher_id} 不在回收站中")
        vh.is_deleted = False
        return vh

    # ══════════════════════════════════════════════════════════════════════════
    # 8. 审核（DRAFT / PENDING_REVIEW → POSTED）
    # ══════════════════════════════════════════════════════════════════════════

    def review(
        self,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
        reviewer_id: int,
        review_note: str | None = None,
    ) -> VoucherHeader:
        vh = self._get_or_404(voucher_id, tenant_id, account_set_id)
        self._check_period_open(vh.voucher_date, tenant_id, account_set_id)

        if vh.is_deleted:
            raise ValueError(f"凭证 {voucher_id} 已软删除，无法审核")
        if vh.review_status == VoucherReviewStatus.POSTED:
            raise VoucherStateError(f"凭证 {voucher_id} 已是 POSTED 状态，无需重复审核")
        if vh.review_status == VoucherReviewStatus.REJECTED:
            raise VoucherStateError(
                f"凭证 {voucher_id} 已被驳回(REJECTED)，请制单人修改后重新提交"
            )

        vh.review_status = VoucherReviewStatus.POSTED
        vh.reviewer_id   = reviewer_id
        vh.review_note   = review_note
        vh.reviewed_at   = datetime.utcnow()
        logger.info("凭证 %s 审核通过，POSTED by user %s", voucher_id, reviewer_id)
        return vh

    # ══════════════════════════════════════════════════════════════════════════
    # 9. 反审核（POSTED → PENDING_REVIEW）
    # ══════════════════════════════════════════════════════════════════════════

    def unreview(
        self,
        voucher_id: int,
        tenant_id: int,
        account_set_id: int,
    ) -> VoucherHeader:
        vh = self._get_or_404(voucher_id, tenant_id, account_set_id)
        self._check_period_open(vh.voucher_date, tenant_id, account_set_id)

        if vh.review_status != VoucherReviewStatus.POSTED:
            raise VoucherStateError(
                f"凭证 {voucher_id} 当前状态为 {vh.review_status}，"
                "只有 POSTED 状态才允许反审核"
            )
        # AuditGuard 已允许 POSTED → PENDING_REVIEW 这一特定路径
        vh.review_status = VoucherReviewStatus.PENDING_REVIEW
        vh.reviewer_id   = None
        vh.review_note   = None
        vh.reviewed_at   = None
        logger.info("凭证 %s 反审核，状态回退为 PENDING_REVIEW", voucher_id)
        return vh

    # ══════════════════════════════════════════════════════════════════════════
    # 10. 断号整理（按会计期间顺序重编 voucher_number）
    # ══════════════════════════════════════════════════════════════════════════

    def reorganize(
        self,
        tenant_id: int,
        account_set_id: int,
        body: ReorganizeInput,
    ) -> ReorganizeResult:
        """
        对指定期间内所有未删除的凭证，按 voucher_date 升序、voucher_id 升序
        重新顺序赋值 voucher_number（从 1 开始）。

        整个操作在调用方的同一事务中执行，失败时由调用方 rollback。
        """
        rows = (
            self._db.query(VoucherHeader)
            .filter(
                VoucherHeader.tenant_id      == tenant_id,
                VoucherHeader.account_set_id == account_set_id,
                VoucherHeader.is_deleted     == False,
                extract("year",  VoucherHeader.voucher_date) == body.period_year,
                extract("month", VoucherHeader.voucher_date) == body.period_month,
            )
            .order_by(
                VoucherHeader.voucher_date.asc(),
                VoucherHeader.voucher_id.asc(),
            )
            .all()
        )

        for idx, vh in enumerate(rows, start=1):
            vh.voucher_number = idx

        period_str = f"{body.period_year:04d}-{body.period_month:02d}"
        logger.info(
            "断号整理：期间 %s 共 %d 条凭证已重新编号", period_str, len(rows)
        )
        return ReorganizeResult(
            period        = period_str,
            updated_count = len(rows),
            message       = f"期间 {period_str} 共 {len(rows)} 条凭证已完成断号整理",
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 11. 确认入账（AI 草稿 → 数据库）
    # ══════════════════════════════════════════════════════════════════════════

    def confirm_ai_draft(
        self,
        tenant_id: int,
        account_set_id: int,
        body: ConfirmVoucherInput,
        creator_id: int | None = None,
    ) -> VoucherHeader:
        """
        将 Sprint 3.1 生成的 AI 草稿写入数据库。

        步骤：
          1. 创建 OperationalRecord（满足 record_id FK，记录原始业务描述）
          2. 创建 VoucherHeader
          3. 逐行解析 auxiliary_data → auxiliary_entity_id（查找或自动创建实体）
          4. 创建 VoucherLine 列表
        """
        self._check_period_open(body.voucher_date, tenant_id, account_set_id)

        # 1. OperationalRecord
        rec = self._create_operational_record(
            body.description, tenant_id, account_set_id
        )

        # 2. VoucherHeader
        debit_total = Decimal(
            str(sum(l.amount for l in body.lines if l.direction == "DEBIT"))
        )
        vh = VoucherHeader(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            record_id      = rec.record_id,
            voucher_date   = body.voucher_date,
            voucher_word   = body.voucher_word,
            total_amount   = debit_total,
            memo           = body.memo,
            creator_id     = creator_id,
            review_status  = VoucherReviewStatus.DRAFT,
            is_deleted     = False,
        )
        self._db.add(vh)
        self._db.flush()

        # 3 & 4. VoucherLines（含 auxiliary_data 解析）
        lines = self._build_lines(
            body.lines, vh.voucher_id, tenant_id, account_set_id,
            has_auxiliary_data=True,
        )
        self._db.add_all(lines)

        logger.info(
            "AI 草稿确认入账：voucher_id=%s，record_id=%s，行数=%d",
            vh.voucher_id, rec.record_id, len(lines),
        )
        return vh
