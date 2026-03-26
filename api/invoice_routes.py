"""
AgentLedger — Invoice API (Phase 5)

发票台账管理端点：
  POST /api/invoices              — 手工录入发票
  GET  /api/invoices              — 列表（支持类型/日期/状态过滤）
  GET  /api/invoices/{id}         — 详情
  PUT  /api/invoices/{id}/link    — 关联到凭证
  PUT  /api/invoices/{id}/verify  — 标记已验真
  DELETE /api/invoices/{id}       — 作废（逻辑删除，status→INVALID）
"""
import logging
from datetime import date as date_type
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from models.invoice import Invoice, InvoiceType, InvoiceStatus, InvoiceSource
from models.user_account import UserAccount, UserRole
from services.auth_service import get_current_user, require_role
from services.audit_service import audit, get_ip, AuditAction

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/invoices", tags=["invoices"])

FINANCE_ROLES = (UserRole.BOSS, UserRole.ACCOUNTANT)


class InvoiceCreate(BaseModel):
    invoice_type:    str           = Field(..., pattern="^(INPUT|OUTPUT)$")
    invoice_code:    str | None    = None
    invoice_number:  str           = Field(..., min_length=1, max_length=20)
    invoice_date:    str           = Field(..., description="YYYY-MM-DD")
    seller_name:     str | None    = None
    seller_tax_id:   str | None    = None
    buyer_name:      str | None    = None
    buyer_tax_id:    str | None    = None
    subtotal_amount: float         = Field(..., gt=0)
    tax_rate:        float         = Field(default=0.0, ge=0, le=1)
    tax_amount:      float         = Field(default=0.0, ge=0)
    total_amount:    float         = Field(..., gt=0)
    items_summary:   str | None    = None


class LinkVoucher(BaseModel):
    voucher_id: int


def _inv_dict(i: Invoice) -> dict:
    return {
        "invoice_id":      i.invoice_id,
        "invoice_type":    i.invoice_type,
        "invoice_code":    i.invoice_code,
        "invoice_number":  i.invoice_number,
        "invoice_date":    str(i.invoice_date),
        "seller_name":     i.seller_name,
        "seller_tax_id":   i.seller_tax_id,
        "buyer_name":      i.buyer_name,
        "buyer_tax_id":    i.buyer_tax_id,
        "subtotal_amount": float(i.subtotal_amount),
        "tax_rate":        float(i.tax_rate),
        "tax_amount":      float(i.tax_amount),
        "total_amount":    float(i.total_amount),
        "items_summary":   i.items_summary,
        "voucher_id":      i.voucher_id,
        "status":          i.status,
        "source":          i.source,
        "image_path":      i.image_path,
        "created_by":      i.created_by,
        "created_at":      str(i.created_at) if i.created_at else None,
    }


@router.post("", status_code=201)
def create_invoice(
    body:         InvoiceCreate,
    request:      Request,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    try:
        inv_date = date_type.fromisoformat(body.invoice_date)
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
        source          = InvoiceSource.MANUAL,
        created_by      = current_user.user_id,
    )
    db.add(inv)
    db.flush()
    audit(db, current_user, "invoice", inv.invoice_id, AuditAction.CREATE,
          after=_inv_dict(inv), desc=f"录入发票 {body.invoice_number}", ip=get_ip(request))
    db.commit()
    logger.info("Invoice created: id=%s by=%s", inv.invoice_id, current_user.username)
    return _inv_dict(inv)


@router.get("")
def list_invoices(
    invoice_type: str | None = None,
    status:       str | None = None,
    date_from:    str | None = None,
    date_to:      str | None = None,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    q = db.query(Invoice).filter(Invoice.status != InvoiceStatus.INVALID)
    if invoice_type:
        q = q.filter(Invoice.invoice_type == invoice_type.upper())
    if status:
        q = q.filter(Invoice.status == status.upper())
    if date_from:
        q = q.filter(Invoice.invoice_date >= date_type.fromisoformat(date_from))
    if date_to:
        q = q.filter(Invoice.invoice_date <= date_type.fromisoformat(date_to))
    items = q.order_by(Invoice.invoice_date.desc()).limit(500).all()
    return [_inv_dict(i) for i in items]


@router.get("/{invoice_id}")
def get_invoice(
    invoice_id:   int,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="发票不存在")
    return _inv_dict(inv)


@router.put("/{invoice_id}/link")
def link_to_voucher(
    invoice_id:   int,
    body:         LinkVoucher,
    request:      Request,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="发票不存在")
    prev = inv.voucher_id
    inv.voucher_id = body.voucher_id
    audit(db, current_user, "invoice", invoice_id, AuditAction.UPDATE,
          before={"voucher_id": prev}, after={"voucher_id": body.voucher_id},
          desc=f"发票关联凭证#{body.voucher_id}", ip=get_ip(request))
    db.commit()
    return _inv_dict(inv)


@router.put("/{invoice_id}/verify")
def verify_invoice(
    invoice_id:   int,
    request:      Request,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="发票不存在")
    if inv.status == InvoiceStatus.INVALID:
        raise HTTPException(status_code=409, detail="已作废发票不可验真")
    prev = inv.status
    inv.status = InvoiceStatus.VERIFIED
    audit(db, current_user, "invoice", invoice_id, AuditAction.STATUS_CHANGE,
          before={"status": prev}, after={"status": inv.status},
          desc="发票标记为已验真", ip=get_ip(request))
    db.commit()
    return _inv_dict(inv)


@router.delete("/{invoice_id}")
def invalidate_invoice(
    invoice_id:   int,
    request:      Request,
    current_user: UserAccount = Depends(require_role(*FINANCE_ROLES)),
    db:           Session     = Depends(get_db),
) -> Any:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="发票不存在")
    if inv.status == InvoiceStatus.INVALID:
        raise HTTPException(status_code=409, detail="发票已经是作废状态")
    prev = inv.status
    inv.status = InvoiceStatus.INVALID
    audit(db, current_user, "invoice", invoice_id, AuditAction.STATUS_CHANGE,
          before={"status": prev}, after={"status": inv.status},
          desc="发票作废", ip=get_ip(request))
    db.commit()
    return {"message": "发票已作废", "invoice_id": invoice_id}
