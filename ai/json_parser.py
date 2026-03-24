"""
AgentLedger — LLM JSON Parser
Safely deserialises the raw string returned by the LLM into a validated
Python dataclass. Raises structured errors so callers can route to MANUAL_REVIEW.
"""
import json
import re
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

ALLOWED_PAYMENT_METHODS = {
    "现金", "银行转账", "微信支付", "支付宝", "员工垫付", "未指定"
}


class JSONParseError(ValueError):
    """Raised when LLM output cannot be parsed or fails validation."""


@dataclass
class ExtractedRecord:
    amount:         Decimal
    currency:       str
    expense_type:   str
    payment_method: str
    payer_name:     str | None
    counterparty:   str | None
    memo:           str
    confidence:     float

    # raw JSON string preserved for storage in operational_record.extracted_json
    raw_json: str = ""


def parse_llm_output(raw_text: str) -> ExtractedRecord:
    """
    Parse and validate the LLM's JSON output.

    Steps:
      1. Strip any accidental Markdown fences.
      2. json.loads() — fail fast on malformed JSON.
      3. Validate required fields and types.
      4. Return a typed ExtractedRecord.
    """
    # ── Step 1: strip Markdown code fences if present ────────────────────────
    cleaned = re.sub(r"```(?:json)?", "", raw_text).strip()

    # ── Step 2: parse JSON ────────────────────────────────────────────────────
    try:
        data: dict = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise JSONParseError(f"LLM returned invalid JSON: {exc}. Raw: {raw_text[:200]}") from exc

    if not isinstance(data, dict):
        raise JSONParseError("LLM JSON root must be an object.")

    # ── Step 3: validate required fields ─────────────────────────────────────
    # amount
    raw_amount = data.get("amount")
    if raw_amount is None:
        raise JSONParseError("Missing required field: 'amount'")
    try:
        amount = Decimal(str(raw_amount))
    except InvalidOperation as exc:
        raise JSONParseError(f"'amount' is not a valid decimal: {raw_amount}") from exc
    if amount <= 0:
        raise JSONParseError(f"'amount' must be positive, got: {amount}")

    # expense_type
    expense_type = data.get("expense_type", "").strip()
    if not expense_type:
        raise JSONParseError("Missing or empty required field: 'expense_type'")

    # payment_method
    payment_method = data.get("payment_method", "未指定").strip()
    if payment_method not in ALLOWED_PAYMENT_METHODS:
        logger.warning("Unknown payment_method '%s', defaulting to '未指定'", payment_method)
        payment_method = "未指定"

    # confidence
    confidence_raw = data.get("confidence", 0.0)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.0

    return ExtractedRecord(
        amount         = amount,
        currency       = str(data.get("currency", "CNY")),
        expense_type   = expense_type,
        payment_method = payment_method,
        payer_name     = data.get("payer_name") or None,
        counterparty   = data.get("counterparty") or None,
        memo           = str(data.get("memo", ""))[:200],
        confidence     = confidence,
        raw_json       = cleaned,
    )
