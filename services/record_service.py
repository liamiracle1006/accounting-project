"""
AgentLedger — RecordService

完整流水处理流程：
  1. 保存原始文本到 operational_record（PENDING）
  2. 调用 LLM 提取结构化 JSON
  3. 调用 TransactionRouter 判断路由方向
     - AUTO      → AccountingEngineService 直接生成凭证 → PROCESSED
     - INTERCEPT → 挂起，状态置为 PENDING_BOSS_DECISION，不生成凭证
  4. 任何异常 → MANUAL_REVIEW + 事务回滚
"""
import logging
from sqlalchemy.orm import Session

from models.operational_record import OperationalRecord, RecordStatus
from ai.llm_client import LLMClient, LLMClientError
from ai.json_parser import parse_llm_output, JSONParseError
from services.accounting_engine import AccountingEngineService, AccountingError
from services.transaction_router import TransactionRouter, RouteDecision

logger = logging.getLogger(__name__)


class RecordService:
    def __init__(self, db: Session) -> None:
        self._db     = db
        self._llm    = LLMClient()
        self._router = TransactionRouter(db)

    def process_raw_text(self, raw_text: str) -> OperationalRecord:
        """
        完整流水处理入口。
        返回最终状态的 OperationalRecord：
          PROCESSED             — 自动记账完成
          PENDING_BOSS_DECISION — 已拦截，等待老板决策
          MANUAL_REVIEW         — 处理失败（调用方可捕获异常获取详情）
        """
        # ── Step 1: 保存原始输入 ─────────────────────────────────────────────
        record = OperationalRecord(
            raw_text=raw_text,
            status=RecordStatus.PENDING,
        )
        self._db.add(record)
        self._db.flush()
        logger.info("Created OperationalRecord id=%s", record.record_id)

        try:
            # ── Step 2: LLM 解析 ──────────────────────────────────────────────
            raw_json  = self._llm.extract_business_data(raw_text)
            extracted = parse_llm_output(raw_json)
            record.extracted_json = extracted.raw_json
            self._db.flush()

            logger.info(
                "Extracted: type=%s amount=%s payment=%s confidence=%.2f",
                extracted.expense_type, extracted.amount,
                extracted.payment_method, extracted.confidence,
            )

            # ── Step 3: 路由判断 ──────────────────────────────────────────────
            decision, intercept_reason = self._router.decide(extracted)

            if decision == RouteDecision.INTERCEPT:
                # 挂起：写入拦截原因，状态置为待老板决策，不生成凭证
                record.status        = RecordStatus.PENDING_BOSS_DECISION
                record.error_message = intercept_reason   # 复用字段存储拦截说明
                self._db.commit()
                logger.info(
                    "Record id=%s intercepted: %s", record.record_id, intercept_reason
                )
                return record

            # ── Step 4: 自动记账 ─────────────────────────────────────────────
            engine = AccountingEngineService(self._db)
            engine.generate_voucher(record, extracted)

            record.status = RecordStatus.PROCESSED
            self._db.commit()
            logger.info("Record id=%s auto-posted successfully", record.record_id)

        except (LLMClientError, JSONParseError, AccountingError, ValueError) as exc:
            self._db.rollback()
            self._db.add(record)
            record.status        = RecordStatus.MANUAL_REVIEW
            record.error_message = str(exc)[:1000]
            self._db.commit()
            logger.warning("Record id=%s flagged for manual review: %s", record.record_id, exc)
            raise

        return record
