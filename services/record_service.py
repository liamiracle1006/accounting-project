"""
AgentLedger — RecordService  (任务 3.1)
Responsibility:
  1. Persist raw_text into operational_record (status=PENDING).
  2. Call LLM to extract structured data.
  3. Update extracted_json on the record.
  4. Hand off to AccountingEngineService for voucher generation.
  5. On any failure: mark record as MANUAL_REVIEW and re-raise.
"""
import logging
from sqlalchemy.orm import Session

from models.operational_record import OperationalRecord, RecordStatus
from ai.llm_client import LLMClient, LLMClientError
from ai.json_parser import parse_llm_output, JSONParseError
from services.accounting_engine import AccountingEngineService

logger = logging.getLogger(__name__)


class RecordService:
    def __init__(self, db: Session) -> None:
        self._db  = db
        self._llm = LLMClient()

    def process_raw_text(self, raw_text: str) -> OperationalRecord:
        """
        Full pipeline: raw text → LLM → JSON → voucher.
        Returns the OperationalRecord in its final state.
        """
        # ── Step 1: persist the raw input ────────────────────────────────────
        record = OperationalRecord(
            raw_text = raw_text,
            status   = RecordStatus.PENDING,
        )
        self._db.add(record)
        self._db.flush()           # get record_id without committing yet
        logger.info("Created OperationalRecord id=%s", record.record_id)

        try:
            # ── Step 2: call LLM ──────────────────────────────────────────────
            raw_json = self._llm.extract_business_data(raw_text)

            # ── Step 3: parse & validate JSON ────────────────────────────────
            extracted = parse_llm_output(raw_json)
            record.extracted_json = extracted.raw_json
            self._db.flush()

            logger.info(
                "Extracted: type=%s amount=%s payment=%s confidence=%.2f",
                extracted.expense_type, extracted.amount,
                extracted.payment_method, extracted.confidence,
            )

            # ── Step 4: generate voucher ─────────────────────────────────────
            engine = AccountingEngineService(self._db)
            engine.generate_voucher(record, extracted)

            # ── Step 5: mark as processed ────────────────────────────────────
            record.status = RecordStatus.PROCESSED
            self._db.commit()
            logger.info("Record id=%s processed successfully", record.record_id)

        except (LLMClientError, JSONParseError, ValueError) as exc:
            self._db.rollback()
            # Re-fetch after rollback to update status in a clean transaction
            self._db.add(record)
            record.status        = RecordStatus.MANUAL_REVIEW
            record.error_message = str(exc)[:1000]
            self._db.commit()
            logger.warning("Record id=%s flagged for manual review: %s",
                           record.record_id, exc)
            raise

        return record
