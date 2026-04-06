"""
AgentLedger V4.0 — ImportSession + ImportStaging ORM Models (Sprint 2.3)

旧账导入状态机：
  UPLOADING  → 文件已上传，Pandas 物理清洗完成，等待 LLM 表头映射
  MAPPING    → 表头映射完成，数据已写入 ImportStaging，等待 AI 科目匹配
  REVIEWING  → AI 匹配完成，存在 PENDING_REVIEW 行，等待人工复核
  COMPLETED  → 所有行确认完毕，数据已结转 InitialBalance

两张表均继承 TenantMixin 保证多租户物理隔离。
"""
import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, Enum as SAEnum, Float, Integer,
    JSON, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database.connection import Base
from models.mixins import TenantMixin


# ── 枚举 ────────────────────────────────────────────────────────────────────────

class ImportSessionStatus(str, enum.Enum):
    UPLOADING  = "UPLOADING"
    MAPPING    = "MAPPING"
    REVIEWING  = "REVIEWING"
    COMPLETED  = "COMPLETED"


class ImportStagingStatus(str, enum.Enum):
    CONFIRMED      = "CONFIRMED"
    PENDING_REVIEW = "PENDING_REVIEW"
    SKIPPED        = "SKIPPED"


# 允许的旧系统类型（与前端向导页联动）
SOURCE_SYSTEM_CHOICES = ("金蝶", "用友", "管家婆", "其他Excel")


# ══════════════════════════════════════════════════════════════════════════════
# 1. ImportSession — 导入会话（每次上传 = 一个会话）
# ══════════════════════════════════════════════════════════════════════════════

class ImportSession(TenantMixin, Base):
    """
    一次旧账导入的全生命周期会话。

    header_mapping: LLM 返回的列名对照表，格式示例：
      {"subject_code": "科目编码", "subject_name": "科目名称",
       "balance_direction": "余额方向", "initial_balance": "期末余额",
       "ytd_debit": "本期借方累计", "ytd_credit": "本期贷方累计"}
    """
    __tablename__ = "import_session"

    session_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
    )
    source_system: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="旧系统类型：金蝶/用友/管家婆/其他Excel",
    )
    status: Mapped[str] = mapped_column(
        SAEnum(
            ImportSessionStatus.UPLOADING.value,
            ImportSessionStatus.MAPPING.value,
            ImportSessionStatus.REVIEWING.value,
            ImportSessionStatus.COMPLETED.value,
            name="import_session_status",
        ),
        nullable=False,
        default=ImportSessionStatus.UPLOADING.value,
    )
    original_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="上传时的原始文件名",
    )
    header_mapping: Mapped[dict | None] = mapped_column(
        JSON, nullable=True, comment="LLM 推断的列名映射",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. ImportStaging — 导入中间表（每行 Excel = 一条记录）
# ══════════════════════════════════════════════════════════════════════════════

class ImportStaging(TenantMixin, Base):
    """
    旧账 Excel 每行数据的中间暂存。

    lifecycle:
      上传清洗后写入（raw_* 字段）
      → AI 科目匹配后更新（match_status / system_subject_code / ai_suggestions）
      → 人工复核确认或跳过
      → execute_import 时将 CONFIRMED 行转换为 InitialBalance

    ai_suggestions 格式：
      [{"code": "1002", "name": "银行存款", "confidence": 0.92}, ...]
    """
    __tablename__ = "import_staging"

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True,
    )
    session_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="FK → import_session.session_id",
    )
    row_number: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="Excel 原始行号（1-based，含表头后从2开始）",
    )

    # ── 原始列值（字符串，Pandas 清洗后的原始字符串，不做任何类型转换）────────
    raw_subject_code:      Mapped[str | None] = mapped_column(String(50),  nullable=True)
    raw_subject_name:      Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_balance_direction: Mapped[str | None] = mapped_column(String(20),  nullable=True)
    raw_initial_balance:   Mapped[str | None] = mapped_column(String(50),  nullable=True)
    raw_ytd_debit:         Mapped[str | None] = mapped_column(String(50),  nullable=True)
    raw_ytd_credit:        Mapped[str | None] = mapped_column(String(50),  nullable=True)

    # ── 解析后的数值（None = 原始值无法解析为数字）───────────────────────────
    parsed_initial_balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_ytd_debit:        Mapped[float | None] = mapped_column(Float, nullable=True)
    parsed_ytd_credit:       Mapped[float | None] = mapped_column(Float, nullable=True)
    # 标准化后的余额方向："借" / "贷" / None（无法识别）
    parsed_balance_direction: Mapped[str | None] = mapped_column(String(2), nullable=True)

    # ── AI 科目匹配结果 ───────────────────────────────────────────────────────
    match_status: Mapped[str] = mapped_column(
        SAEnum(
            ImportStagingStatus.CONFIRMED.value,
            ImportStagingStatus.PENDING_REVIEW.value,
            ImportStagingStatus.SKIPPED.value,
            name="import_staging_status",
        ),
        nullable=False,
        default=ImportStagingStatus.PENDING_REVIEW.value,
        comment="CONFIRMED=确认 / PENDING_REVIEW=待复核 / SKIPPED=跳过",
    )
    match_confidence: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="AI 匹配置信度 0.0~1.0",
    )
    system_subject_code: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="最终匹配或人工指定的系统科目编码",
    )
    ai_suggestions: Mapped[list | None] = mapped_column(
        JSON, nullable=True, comment="AI 建议的最多3个候选科目列表",
    )
    skip_reason: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="SKIPPED 行的原因说明",
    )
