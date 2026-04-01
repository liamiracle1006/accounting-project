from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from database.connection import Base
from models.mixins import TenantMixin


class RecordStatus:
    PENDING                = "PENDING"                 # 刚收到，等待 LLM 处理
    PROCESSED              = "PROCESSED"               # 自动记账完成（小额普通流水）
    PENDING_BOSS_DECISION  = "PENDING_BOSS_DECISION"   # 大额/敏感流水，等待老板决策
    MANUAL_REVIEW          = "MANUAL_REVIEW"           # AI 解析失败或日常分录不平，需人工介入


class OperationalRecord(TenantMixin, Base):
    __tablename__ = "operational_record"

    record_id:      Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    raw_text:       Mapped[str] = mapped_column(Text, nullable=False)
    extracted_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status:         Mapped[str] = mapped_column(String(30), nullable=False,
                                                default=RecordStatus.PENDING)
    error_message:  Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at      = mapped_column(DateTime, server_default=func.now())
    updated_at      = mapped_column(DateTime, server_default=func.now(),
                                    onupdate=func.now())

    def __repr__(self) -> str:
        return f"<OperationalRecord {self.record_id} [{self.status}]>"
