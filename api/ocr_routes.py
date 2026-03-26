"""
AgentLedger — OCR / Import API (Phase 5)

端点：
  POST /api/ocr/invoice          — 上传发票图片，返回识别结果（不自动入库）
  POST /api/ocr/invoice/confirm  — 确认识别结果，正式写入发票台账
  POST /api/ocr/bank-csv         — 上传银行流水 CSV，返回解析结果
  POST /api/ocr/bank-csv/import  — 确认银行流水，批量生成待审核凭证
"""
import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database.connection import get_db
from models.invoice import Invoice, InvoiceStatus, InvoiceSource, InvoiceType
from models.user_account import UserAccount, UserRole
from services.auth_service import get_current_user, require_role
from services.audit_service import audit, get_ip, AuditAction
from services.ocr_service import recognize_invoice, parse_bank_csv, BankTransaction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ocr", tags=["ocr"])

FINANCE_ROLES = (UserRole.BOSS, UserRole.ACCOUNTANT)

_ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
_MAX_IMAGE_SIZE      = 10 * 1024 * 1024   # 10 MB
_MAX_CSV_SIZE        = 5  * 1024 * 1024   # 5 MB


# ── 发票 OCR ────────────────────────────────────────────────────────────────

@router.post("/invoice")
async def ocr_invoice(
    file:         UploadFile = File(..., description="发票图片（JPG/PNG/WEBP，≤10MB）"),
    invoice_type: str        = "INPUT",
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
) -> Any:
    """
    上传发票图片，返回 OCR 识别结果供人工确认。
    不自动入库，需调用 /confirm 接口确认后才写入台账。

    【当前状态】视觉 LLM 未接入，返回空字段。
    接入方法见 services/ocr_service.py 中的 _call_vision_llm() 注释。
    """
    if file.content_type not in _ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail=f"不支持的文件类型：{file.content_type}，请上传 JPG/PNG/WEBP")

    image_bytes = await file.read()
    if len(image_bytes) > _MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="图片超过 10MB 限制")

    inv_type = invoice_type.upper()
    if inv_type not in ("INPUT", "OUTPUT"):
        raise HTTPException(status_code=422, detail="invoice_type 须为 INPUT 或 OUTPUT")

    result = recognize_invoice(image_bytes, file.content_type, inv_type)

    return {
        "ocr_configured": bool(result.confidence > 0),
        "confidence":     result.confidence,
        "result": {
            "invoice_type":    result.invoice_type,
            "invoice_code":    result.invoice_code,
            "invoice_number":  result.invoice_number,
            "invoice_date":    result.invoice_date,
            "seller_name":     result.seller_name,
            "seller_tax_id":   result.seller_tax_id,
            "buyer_name":      result.buyer_name,
            "buyer_tax_id":    result.buyer_tax_id,
            "subtotal_amount": result.subtotal_amount,
            "tax_rate":        result.tax_rate,
            "tax_amount":      result.tax_amount,
            "total_amount":    result.total_amount,
            "items_summary":   result.items_summary,
        },
        "notice": None if result.confidence > 0 else
                  "视觉 LLM 未配置，返回空结果。请参考 services/ocr_service.py 接入说明。",
    }


class InvoiceConfirm(BaseModel):
    invoice_type:    str
    invoice_code:    str | None   = None
    invoice_number:  str
    invoice_date:    str
    seller_name:     str | None   = None
    seller_tax_id:   str | None   = None
    buyer_name:      str | None   = None
    buyer_tax_id:    str | None   = None
    subtotal_amount: float
    tax_rate:        float        = 0.0
    tax_amount:      float        = 0.0
    total_amount:    float
    items_summary:   str | None   = None


@router.post("/invoice/confirm", status_code=201)
def confirm_invoice(
    body:         InvoiceConfirm,
    request:      Request,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    """将人工校对后的 OCR 结果正式写入发票台账（source=OCR）。"""
    from datetime import date as dt
    try:
        inv_date = dt.fromisoformat(body.invoice_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="invoice_date 格式应为 YYYY-MM-DD")

    inv = Invoice(
        invoice_type    = body.invoice_type,
        invoice_code    = body.invoice_code,
        invoice_number  = body.invoice_number,
        invoice_date    = inv_date,
        seller_name     = body.seller_name,
        seller_tax_id   = body.seller_tax_id,
        buyer_name      = body.buyer_name,
        buyer_tax_id    = body.buyer_tax_id,
        subtotal_amount = Decimal(str(body.subtotal_amount)),
        tax_rate        = Decimal(str(body.tax_rate)),
        tax_amount      = Decimal(str(body.tax_amount)),
        total_amount    = Decimal(str(body.total_amount)),
        items_summary   = body.items_summary,
        status          = InvoiceStatus.UNVERIFIED,
        source          = InvoiceSource.OCR,
        created_by      = current_user.user_id,
    )
    db.add(inv)
    db.flush()
    audit(db, current_user, "invoice", inv.invoice_id, AuditAction.CREATE,
          after={"source": "OCR", "invoice_number": body.invoice_number},
          desc=f"OCR 识别发票入库 {body.invoice_number}",
          ip=get_ip(request))
    db.commit()
    logger.info("Invoice confirmed from OCR: id=%s by=%s", inv.invoice_id, current_user.username)
    return {"invoice_id": inv.invoice_id, "message": "发票已入库，状态：待验真"}


# ── 银行流水 CSV ────────────────────────────────────────────────────────────

@router.post("/bank-csv")
async def parse_bank_csv_upload(
    file:         UploadFile = File(..., description="银行流水 CSV（≤5MB，UTF-8 或 GBK 编码）"),
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
) -> Any:
    """
    上传银行流水 CSV，返回解析结果供人工确认。
    支持招商/工行/建行等常见导出格式，自动检测编码和列名。
    """
    if file.content_type not in ("text/csv", "application/vnd.ms-excel",
                                  "text/plain", "application/octet-stream"):
        # content_type 不可靠，只警告不拦截
        logger.warning("Unexpected CSV content-type: %s", file.content_type)

    csv_bytes = await file.read()
    if len(csv_bytes) > _MAX_CSV_SIZE:
        raise HTTPException(status_code=413, detail="CSV 文件超过 5MB 限制")

    txns = parse_bank_csv(csv_bytes)

    if not txns:
        return {"count": 0, "transactions": [],
                "notice": "未能解析任何交易记录。请确认 CSV 格式符合常见银行导出规范。"}

    return {
        "count": len(txns),
        "transactions": [
            {
                "trans_date":  str(t.trans_date),
                "amount":      float(t.amount),
                "direction":   "IN" if t.amount > 0 else "OUT",
                "description": t.description,
                "balance":     float(t.balance) if t.balance is not None else None,
                "counterpart": t.counterpart,
            }
            for t in txns
        ],
    }


class BankImportLine(BaseModel):
    trans_date:  str
    amount:      float
    description: str
    counterpart: str | None = None


class BankImportRequest(BaseModel):
    transactions: list[BankImportLine]


@router.post("/bank-csv/import", status_code=201)
def import_bank_transactions(
    body:         BankImportRequest,
    request:      Request,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    """
    将确认后的银行流水批量生成自然语言 operational_record，
    触发 LLM 智能记账流程（状态：待处理），供财务人员后续在工作台审核。
    """
    from datetime import date as dt
    from models.operational_record import OperationalRecord

    created = []
    for t in body.transactions:
        try:
            txn_date = dt.fromisoformat(t.trans_date)
        except ValueError:
            continue

        direction = "收入" if t.amount > 0 else "支出"
        amount    = abs(t.amount)
        counterpart_note = f"（对方：{t.counterpart}）" if t.counterpart else ""
        nl_text = f"{txn_date} 银行{direction} ¥{amount:.2f}，摘要：{t.description}{counterpart_note}"

        record = OperationalRecord(
            raw_text = nl_text,
            status   = "PENDING",
        )
        db.add(record)
        created.append(nl_text)

    db.flush()
    audit(db, current_user, "operational_record", "batch", AuditAction.CREATE,
          after={"count": len(created)},
          desc=f"银行流水批量导入 {len(created)} 笔",
          ip=get_ip(request))
    db.commit()
    logger.info("Bank import: %d records created by=%s", len(created), current_user.username)
    return {"imported": len(created), "message": f"已生成 {len(created)} 条待处理流水，请前往流水记录处理"}
