"""
AgentLedger — OCR Service (Phase 5)

发票图片识别 + 银行流水 CSV 解析。

【OCR 调用说明】
  当前 _call_vision_llm() 为占位实现，返回空结构。
  接入步骤：
    1. 在 config/settings.py 添加：
         VISION_API_KEY  = os.getenv("VISION_API_KEY", "")
         VISION_API_BASE = os.getenv("VISION_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
         VISION_MODEL    = os.getenv("VISION_MODEL", "qwen-vl-max")
    2. 将本文件中 _call_vision_llm() 的占位代码替换为真实 API 调用。
    3. 参考注释中的 curl 示例验证接口可用性。

【银行流水 CSV 规范】
  支持常见银行导出格式（招行/工行/建行）。
  必要列：交易日期、借贷标志或金额（正=入账 负=支出）、摘要/用途。
  可选列：余额、对手账号、对手名称。
"""
import csv
import io
import json
import logging
import base64
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from config.settings import VISION_API_KEY, VISION_API_BASE, VISION_MODEL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class InvoiceOCRResult:
    """OCR 识别的发票结构化结果"""
    invoice_type:    str          = "INPUT"   # INPUT/OUTPUT
    invoice_code:    str | None   = None
    invoice_number:  str          = ""
    invoice_date:    str          = ""        # YYYY-MM-DD
    seller_name:     str | None   = None
    seller_tax_id:   str | None   = None
    buyer_name:      str | None   = None
    buyer_tax_id:    str | None   = None
    subtotal_amount: float        = 0.0
    tax_rate:        float        = 0.13
    tax_amount:      float        = 0.0
    total_amount:    float        = 0.0
    items_summary:   str | None   = None
    confidence:      float        = 0.0       # 识别置信度 0~1
    raw_text:        str | None   = None      # LLM 返回原文，供调试


@dataclass
class BankTransaction:
    """银行流水单条记录"""
    trans_date:  date
    amount:      Decimal          # 正=收入 负=支出
    description: str
    balance:     Decimal | None   = None
    counterpart: str | None       = None      # 对手方名称


# ---------------------------------------------------------------------------
# 占位 Vision LLM 调用（待接入真实 API）
# ---------------------------------------------------------------------------

# 默认发票识别 Prompt（保持原有行为）
_DEFAULT_INVOICE_PROMPT = (
    "请识别这张增值税发票，提取所有字段，"
    "以 JSON 格式返回，字段名使用英文，"
    "金额为数字类型，日期格式为 YYYY-MM-DD，税率为小数（如0.13）。"
    "只返回 JSON，不要任何说明文字。"
)


def _call_vision_llm(
    image_bytes: bytes,
    mime_type:   str,
    prompt:      str | None = None,
) -> str:
    """
    ★ 占位实现 — 接入真实视觉 LLM 时替换此函数 ★

    参数：
      image_bytes — 图片/PDF 的原始字节
      mime_type   — MIME 类型（image/jpeg / image/png / application/pdf 等）
      prompt      — 自定义 Prompt；为 None 时使用默认发票识别 Prompt

    默认（prompt=None）：识别增值税发票，返回发票结构化 JSON（保持原有行为）。
    自定义（prompt 非 None）：由调用方（如 vision_service）注入批量票据提取 Prompt，
                              API key 未配置时返回空 JSON 数组 "[]"。

    ------ 接入参考（通义千问 Qwen-VL-Max）------
    import openai, base64
    from config.settings import VISION_API_KEY, VISION_API_BASE, VISION_MODEL

    client = openai.OpenAI(api_key=VISION_API_KEY, base_url=VISION_API_BASE)
    b64    = base64.b64encode(image_bytes).decode()
    resp   = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"}
                },
                {
                    "type": "text",
                    "text": (
                        "请识别这张增值税发票，提取所有字段，"
                        "以 JSON 格式返回，字段名使用英文，"
                        "金额为数字类型，日期格式为 YYYY-MM-DD。"
                        "只返回 JSON，不要其他说明文字。"
                    )
                }
            ]
        }],
        max_tokens=512,
    )
    return resp.choices[0].message.content
    ------------------------------------------------
    """
    effective_prompt = prompt if prompt is not None else _DEFAULT_INVOICE_PROMPT

    if not VISION_API_KEY:
        logger.warning("VISION_API_KEY not set — OCR returning empty result. "
                       "Set VISION_API_KEY in .env to enable.")
        if prompt is not None:
            return "[]"    # 自定义 Prompt → 返回空数组，上层按无数据处理
        return json.dumps({
            "invoice_code": None, "invoice_number": "",
            "invoice_date": str(date.today()),
            "seller_name": None, "seller_tax_id": None,
            "buyer_name": None,  "buyer_tax_id": None,
            "subtotal_amount": 0.0, "tax_rate": 0.0,
            "tax_amount": 0.0, "total_amount": 0.0,
            "items_summary": None,
        })

    import openai
    b64    = base64.b64encode(image_bytes).decode()
    client = openai.OpenAI(api_key=VISION_API_KEY, base_url=VISION_API_BASE)
    # 自定义 Prompt（批量票据）可能返回多条，给足 token
    max_tokens = 1024 if prompt is not None else 512
    resp   = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                {"type": "text", "text": effective_prompt},
            ],
        }],
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content


# ---------------------------------------------------------------------------
# 发票 OCR 识别
# ---------------------------------------------------------------------------

def recognize_invoice(image_bytes: bytes, mime_type: str = "image/jpeg",
                      invoice_type: str = "INPUT") -> InvoiceOCRResult:
    """
    识别发票图片，返回结构化的 InvoiceOCRResult。
    mime_type: image/jpeg | image/png | image/webp
    """
    try:
        raw = _call_vision_llm(image_bytes, mime_type)
        data: dict[str, Any] = json.loads(raw)
    except Exception as e:
        logger.error("OCR parse error: %s", e)
        data = {}

    def _f(key, default=None):
        return data.get(key, default)

    result = InvoiceOCRResult(
        invoice_type    = invoice_type,
        invoice_code    = _f("invoice_code"),
        invoice_number  = str(_f("invoice_number", "")),
        invoice_date    = _f("invoice_date", str(date.today())),
        seller_name     = _f("seller_name"),
        seller_tax_id   = _f("seller_tax_id"),
        buyer_name      = _f("buyer_name"),
        buyer_tax_id    = _f("buyer_tax_id"),
        subtotal_amount = float(_f("subtotal_amount", 0) or 0),
        tax_rate        = float(_f("tax_rate", 0.13) or 0.13),
        tax_amount      = float(_f("tax_amount", 0) or 0),
        total_amount    = float(_f("total_amount", 0) or 0),
        items_summary   = _f("items_summary"),
        confidence      = 1.0 if data.get("invoice_number") else 0.0,
        raw_text        = raw,
    )
    return result


# ---------------------------------------------------------------------------
# 银行流水 CSV 解析
# ---------------------------------------------------------------------------

# 各银行 CSV 列名映射（可扩展）
_BANK_COLUMN_MAPS = [
    # 招商银行
    {
        "date":        ["交易日期", "记账日期", "Transaction Date"],
        "debit":       ["支出金额", "借方发生额"],
        "credit":      ["收入金额", "贷方发生额"],
        "amount":      [],
        "description": ["交易摘要", "用途", "摘要", "备注"],
        "balance":     ["账户余额", "余额"],
        "counterpart": ["对方户名", "对手方名称"],
    },
    # 工商银行 / 建设银行（金额单列，正负表示方向）
    {
        "date":        ["交易日期", "日期"],
        "debit":       [],
        "credit":      [],
        "amount":      ["交易金额", "金额", "发生额"],
        "description": ["交易用途", "摘要", "用途"],
        "balance":     ["账户余额", "余额", "当前余额"],
        "counterpart": ["对方账号名称", "收款人名称"],
    },
]


def _match_col(headers: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in headers:
            return c
    return None


def parse_bank_csv(csv_content: str | bytes) -> list[BankTransaction]:
    """
    解析银行导出的 CSV 流水，返回 BankTransaction 列表。
    自动尝试多种列名映射方案。
    """
    if isinstance(csv_content, bytes):
        # 尝试 UTF-8 / GBK 解码
        for enc in ("utf-8-sig", "gbk", "gb2312", "utf-8"):
            try:
                csv_content = csv_content.decode(enc)
                break
            except UnicodeDecodeError:
                continue

    reader  = csv.DictReader(io.StringIO(csv_content))
    headers = reader.fieldnames or []

    # 选择最匹配的列名方案
    best_map = None
    best_score = -1
    for col_map in _BANK_COLUMN_MAPS:
        score = sum(1 for k, v in col_map.items()
                    if any(c in headers for c in v))
        if score > best_score:
            best_score = score
            best_map = col_map

    if not best_map:
        logger.warning("Bank CSV: no matching column map found")
        return []

    col_date  = _match_col(headers, best_map["date"])
    col_debit = _match_col(headers, best_map["debit"])
    col_cred  = _match_col(headers, best_map["credit"])
    col_amt   = _match_col(headers, best_map["amount"])
    col_desc  = _match_col(headers, best_map["description"])
    col_bal   = _match_col(headers, best_map["balance"])
    col_cpart = _match_col(headers, best_map["counterpart"])

    transactions: list[BankTransaction] = []

    for row in reader:
        # 解析日期
        date_str = row.get(col_date, "").strip() if col_date else ""
        trans_date = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y.%m.%d"):
            try:
                from datetime import datetime as dt
                trans_date = dt.strptime(date_str, fmt).date()
                break
            except ValueError:
                continue
        if not trans_date:
            continue  # 跳过无法解析日期的行

        # 解析金额
        def _clean(s: str) -> Decimal:
            return Decimal(s.replace(",", "").replace(" ", "") or "0")

        if col_amt:
            try:
                amount = _clean(row.get(col_amt, "0"))
            except Exception:
                amount = Decimal("0")
        else:
            try:
                debit  = _clean(row.get(col_debit, "0") if col_debit else "0")
                credit = _clean(row.get(col_cred,  "0") if col_cred  else "0")
                amount = credit - debit   # 正=收入 负=支出
            except Exception:
                amount = Decimal("0")

        if amount == 0:
            continue

        description = row.get(col_desc, "").strip() if col_desc else ""
        balance     = None
        if col_bal:
            try:
                balance = _clean(row.get(col_bal, ""))
            except Exception:
                pass
        counterpart = row.get(col_cpart, "").strip() if col_cpart else None

        transactions.append(BankTransaction(
            trans_date  = trans_date,
            amount      = amount,
            description = description,
            balance     = balance,
            counterpart = counterpart or None,
        ))

    logger.info("Bank CSV parsed: %d transactions", len(transactions))
    return transactions
