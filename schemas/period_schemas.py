"""
AgentLedger V4.0 — Period (会计期间) Schemas (Sprint 3.3)
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PeriodOut(BaseModel):
    period_id:          int
    year:               int
    month:              int
    status:             str          # OPEN | CLOSED
    closed_at:          Optional[datetime] = None
    closed_by:          Optional[int]      = None
    closing_voucher_id: Optional[int]      = None

    class Config:
        from_attributes = True


class TransferPnLResult(BaseModel):
    year:       int
    month:      int
    net_profit: float
    voucher_id: int
    message:    str


class CloseResult(BaseModel):
    year:              int
    month:             int
    reorganized_count: int
    next_period_year:  int
    next_period_month: int
    message:           str


class UncloseResult(BaseModel):
    year:    int
    month:   int
    message: str
