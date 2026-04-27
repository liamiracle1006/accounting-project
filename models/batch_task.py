"""
AgentLedger V4.0 — BatchImportTask / BatchImportRecord (Sprint 3.5)

两张表构成批处理的状态机基建：

  BatchImportTask   — 任务级：整体状态与进度统计
  BatchImportRecord — 记录级：每张票据的处理结果

状态流转：
  PENDING → PROCESSING → COMPLETED
                       ↘ FAILED（整批流水线崩溃时）

needs_review 设计决策（Sprint 3.5 架构裁决）：
  不修改 VoucherHeader（保持核心凭证表干净，零 DB 迁移风险）。
  needs_review=True 仅存在于 BatchImportRecord，VoucherHeader 保持 DRAFT 状态。
  前端的"黄灯"渲染完全依赖 GET /task/{id}/results 的数据。

两表均继承 TenantMixin（tenant_id + account_set_id），
与其余所有业务表保持一致的多租户隔离规范。
"""
import enum

from sqlalchemy import BigInteger, Boolean, Integer, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.connection import Base
from models.mixins import TenantMixin


class TaskStatus(str, enum.Enum):
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED  = "COMPLETED"
    FAILED     = "FAILED"


class BatchImportTask(TenantMixin, Base):
    """
    批量导入任务（任务级状态机）。

    通过 POST /api/batch/execute 创建，初始状态 PENDING。
    后台 run_batch_pipeline 完成后更新为 COMPLETED 或 FAILED。
    """
    __tablename__ = "batch_import_task"

    task_id:            Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    status              = mapped_column(String(20), nullable=False, default=TaskStatus.PENDING)
    total_count:        Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count:      Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count:        Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    creator_id          = mapped_column(BigInteger, nullable=True)   # 制单人 FK
    created_at          = mapped_column(DateTime, server_default=func.now())
    updated_at          = mapped_column(DateTime, nullable=True)

    records = relationship(
        "BatchImportRecord", back_populates="task", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<BatchImportTask {self.task_id} "
            f"status={self.status} total={self.total_count}>"
        )


class BatchImportRecord(TenantMixin, Base):
    """
    批量导入的单条记录（票据级）。

    raw_data    — StandardReceiptItem 的 JSON 字符串（入库时快照）
    confidence  — HIGH/MEDIUM/LOW（由 ai_voucher_service.generate_voucher 返回）
    voucher_id  — 入账成功后绑定的 VoucherHeader.voucher_id（nullable）
    needs_review — True=黄灯（MEDIUM/LOW 置信度），False=绿灯（HIGH）
    error_msg   — 处理失败时的错误摘要（红灯，varchar 1000）
    """
    __tablename__ = "batch_import_record"

    id:           Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id       = mapped_column(
        Integer, ForeignKey("batch_import_task.task_id"), nullable=False, index=True
    )
    raw_data      = mapped_column(Text,        nullable=False, comment="StandardReceiptItem JSON")
    confidence    = mapped_column(String(10),  nullable=True,  comment="HIGH/MEDIUM/LOW")
    voucher_id    = mapped_column(Integer,     nullable=True,  comment="入账成功后的凭证 ID")
    needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True=黄灯（MEDIUM/LOW 置信度，需人工复核）"
    )
    error_msg     = mapped_column(String(1000), nullable=True, comment="红灯错误摘要")

    task = relationship("BatchImportTask", back_populates="records")

    def __repr__(self) -> str:
        return (
            f"<BatchImportRecord {self.id} "
            f"task={self.task_id} confidence={self.confidence}>"
        )
