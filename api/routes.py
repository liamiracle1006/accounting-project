"""
AgentLedger — RESTful API Routes  (任务 4.1)

Endpoints:
  POST /api/records          — 提交自然语言流水，触发全流程
  GET  /api/records/{id}     — 查询单条流水状态
  GET  /api/records          — 分页查询流水列表
  GET  /api/vouchers/{id}    — 查询凭证详情（含借贷明细）
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database.connection import get_db
from models.operational_record import OperationalRecord, RecordStatus
from models.voucher_header import VoucherHeader
from models.voucher_line import VoucherLine
from services.record_service import RecordService
from ai.llm_client import LLMClientError
from ai.json_parser import JSONParseError
from services.accounting_engine import AccountingError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["accounting"])


# ── Request / Response schemas ────────────────────────────────────────────────

class CreateRecordRequest(BaseModel):
    raw_text: str

    @field_validator("raw_text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("raw_text must not be empty")
        if len(v) > 2000:
            raise ValueError("raw_text must not exceed 2000 characters")
        return v


class RecordResponse(BaseModel):
    record_id:      int
    status:         str
    raw_text:       str
    extracted_json: str | None
    error_message:  str | None

    model_config = {"from_attributes": True}


class VoucherLineResponse(BaseModel):
    line_id:             int
    subject_code:        str
    direction:           str
    amount:              float
    auxiliary_entity_id: int | None
    memo:                str | None

    model_config = {"from_attributes": True}


class VoucherResponse(BaseModel):
    voucher_id:   int
    record_id:    int
    voucher_date: str
    total_amount: float
    memo:         str | None
    lines:        list[VoucherLineResponse]

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/records", response_model=RecordResponse, status_code=201)
def create_record(
    body: CreateRecordRequest,
    db:   Session = Depends(get_db),
) -> Any:
    """
    接收自然语言业务流水，完整执行：
    LLM 解析 → JSON 校验 → 会计映射 → 复式记账凭证入库
    """
    service = RecordService(db)
    try:
        record = service.process_raw_text(body.raw_text)
    except (LLMClientError, JSONParseError, AccountingError, ValueError) as exc:
        # Record has already been saved with MANUAL_REVIEW status; return 422
        logger.warning("Processing failed for raw_text='%s...': %s",
                       body.raw_text[:50], exc)
        raise HTTPException(status_code=422, detail=str(exc))

    return record


@router.get("/records", response_model=list[RecordResponse])
def list_records(
    status: str | None = Query(None, description="过滤状态：PENDING/PROCESSED/MANUAL_REVIEW"),
    skip:   int        = Query(0, ge=0),
    limit:  int        = Query(20, ge=1, le=100),
    db:     Session    = Depends(get_db),
) -> Any:
    """分页查询业务流水列表，可按状态过滤。"""
    q = db.query(OperationalRecord)
    if status:
        q = q.filter(OperationalRecord.status == status.upper())
    return q.order_by(OperationalRecord.record_id.desc()).offset(skip).limit(limit).all()


@router.get("/records/{record_id}", response_model=RecordResponse)
def get_record(record_id: int, db: Session = Depends(get_db)) -> Any:
    """查询单条业务流水。"""
    record = db.get(OperationalRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Record {record_id} not found")
    return record


@router.get("/vouchers/{voucher_id}", response_model=VoucherResponse)
def get_voucher(voucher_id: int, db: Session = Depends(get_db)) -> Any:
    """查询凭证主表 + 借贷明细（支持穿透审计回溯原始流水）。"""
    voucher = db.get(VoucherHeader, voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail=f"Voucher {voucher_id} not found")

    lines = (
        db.query(VoucherLine)
        .filter(VoucherLine.voucher_id == voucher_id)
        .all()
    )
    return {
        "voucher_id":   voucher.voucher_id,
        "record_id":    voucher.record_id,
        "voucher_date": str(voucher.voucher_date),
        "total_amount": float(voucher.total_amount),
        "memo":         voucher.memo,
        "lines": [
            {
                "line_id":             l.line_id,
                "subject_code":        l.subject_code,
                "direction":           l.direction,
                "amount":              float(l.amount),
                "auxiliary_entity_id": l.auxiliary_entity_id,
                "memo":                l.memo,
            }
            for l in lines
        ],
    }
