"""
AgentLedger — AuditGuard (ver3/S1-D)

两个职责：
  1. SQLAlchemy 事件拦截器：阻止对 POSTED 凭证进行删除或状态降级
  2. AuditLog 写入工具函数：在关键业务节点快速记录审计轨迹

使用方法：
  在 main.py / 应用启动时调用 register_voucher_guard() 一次即可。
  写审计日志调用 write_audit_log(db, ...) 。
"""
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── 1. POSTED 凭证防篡改拦截器 ───────────────────────────────────────────────

def register_voucher_guard() -> None:
    """
    注册 SQLAlchemy ORM 事件监听器，在以下情况抛出 PermissionError：
      - 删除 review_status=POSTED 的 VoucherHeader
      - 将 review_status 从 POSTED 降级为其他状态
      - 修改 POSTED 凭证的金额、日期

    注意：监听器是进程级全局的，只需在应用启动时调用一次。
    """
    # 延迟导入避免循环依赖
    from models.voucher_header import VoucherHeader, VoucherReviewStatus
    from models.voucher_line import VoucherLine

    # ── 1a. 防止删除 POSTED 凭证头 ──────────────────────────────────────────
    @event.listens_for(VoucherHeader, "before_delete")
    def _guard_voucher_delete(mapper, connection, target: VoucherHeader):
        if getattr(target, "review_status", None) == VoucherReviewStatus.POSTED:
            raise PermissionError(
                f"凭证 {target.voucher_id} 已过账(POSTED)，禁止删除。"
                "如需冲销请使用红字凭证。"
            )

    # ── 1b. 防止 POSTED 凭证状态降级 / 金额日期篡改 ─────────────────────────
    @event.listens_for(VoucherHeader, "before_update")
    def _guard_voucher_update(mapper, connection, target: VoucherHeader):
        # 获取数据库中当前值（实例历史状态）
        history = mapper.attrs.review_status.class_attribute.__get__(target, type(target))
        # SQLAlchemy inspect 获取变更前的值
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(target)

        status_hist = insp.attrs.review_status.history
        if status_hist.deleted:
            old_status = status_hist.deleted[0]
            new_status = status_hist.added[0] if status_hist.added else target.review_status
            # 允许 POSTED → PENDING_REVIEW（反审核，由 VoucherService.unreview() 发起）
            # 其余 POSTED 降级（如 POSTED → DRAFT、POSTED → REJECTED）一律拒绝
            _allowed_posted_downgrades = {VoucherReviewStatus.PENDING_REVIEW}
            if (old_status == VoucherReviewStatus.POSTED
                    and new_status != VoucherReviewStatus.POSTED
                    and new_status not in _allowed_posted_downgrades):
                raise PermissionError(
                    f"凭证 {target.voucher_id} 已过账(POSTED)，"
                    f"禁止将状态从 POSTED 改为 {new_status}。"
                    "如需反审核，请通过「反审核」接口操作（POSTED → PENDING_REVIEW）。"
                )

        # 防止修改已过账凭证的金额或日期
        if target.review_status == VoucherReviewStatus.POSTED:
            for field in ("total_amount", "voucher_date"):
                hist = getattr(insp.attrs, field).history
                if hist.deleted and hist.added:
                    old_val, new_val = hist.deleted[0], hist.added[0]
                    if old_val != new_val:
                        raise PermissionError(
                            f"凭证 {target.voucher_id} 已过账(POSTED)，"
                            f"禁止修改字段 {field}（{old_val} → {new_val}）。"
                        )

    # ── 1c. 防止删除 POSTED 凭证的明细行 ────────────────────────────────────
    @event.listens_for(VoucherLine, "before_delete")
    def _guard_line_delete(mapper, connection, target: VoucherLine):
        # 通过 Session 查询 parent header 状态
        session: Session = Session.object_session(target)
        if session is None:
            return
        from models.voucher_header import VoucherHeader, VoucherReviewStatus
        header = session.get(VoucherHeader, target.voucher_id)
        if header and header.review_status == VoucherReviewStatus.POSTED:
            raise PermissionError(
                f"凭证 {target.voucher_id} 已过账(POSTED)，禁止删除其明细行。"
            )

    logger.info("VoucherGuard: POSTED 凭证防篡改监听器已注册")


# ── 2. AuditLog 写入工具 ─────────────────────────────────────────────────────

def write_audit_log(
    db:           Session,
    table_name:   str,
    record_id:    Any,
    action:       str,
    description:  str | None = None,
    before_value: dict | None = None,
    after_value:  dict | None = None,
    user_id:      int | None = None,
    username:     str | None = None,
    ip_address:   str | None = None,
) -> None:
    """
    写入一条审计日志。

    示例调用：
        write_audit_log(
            db, "voucher_header", voucher_id,
            action="STATUS_CHANGE",
            description=f"凭证状态变更 DRAFT → POSTED",
            before_value={"review_status": "DRAFT"},
            after_value={"review_status": "POSTED"},
            username="system",
        )
    """
    from models.audit_log import AuditLog
    log = AuditLog(
        table_name   = table_name,
        record_id    = str(record_id),
        action       = action,
        user_id      = user_id,
        username     = username or "system",
        before_value = before_value,
        after_value  = after_value,
        description  = description,
        ip_address   = ip_address,
    )
    db.add(log)
    # 不单独 commit：调用方负责事务边界


# ── 3. 关键节点审计装饰器（可选快捷用法） ────────────────────────────────────

def audit_voucher_posted(db: Session, voucher_id: int, username: str = "system") -> None:
    """凭证状态设为 POSTED 时调用"""
    write_audit_log(
        db, "voucher_header", voucher_id,
        action      = "STATUS_CHANGE",
        description = f"凭证 {voucher_id} 状态变更为 POSTED（正式入账）",
        before_value= {"review_status": "DRAFT"},
        after_value = {"review_status": "POSTED"},
        username    = username,
    )


def audit_period_closed(db: Session, period: str, username: str = "system") -> None:
    """期末结账完成时调用"""
    write_audit_log(
        db, "accounting_period", period,
        action      = "STATUS_CHANGE",
        description = f"期间 {period} 结账完成",
        after_value = {"status": "CLOSED", "period": period},
        username    = username,
    )


def audit_boss_decision(db: Session, log_id: int, option: str, username: str = "boss") -> None:
    """老板执行决策时调用"""
    write_audit_log(
        db, "boss_decision_log", log_id,
        action      = "UPDATE",
        description = f"老板决策执行：选择方案 {option}",
        after_value = {"chosen_option": option},
        username    = username,
    )
