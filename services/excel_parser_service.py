"""
AgentLedger V4.0 — Excel/CSV 解析引擎 (Sprint 3.5)

职责：
  接收 FastAPI UploadFile（.xlsx / .xls / .csv），
  智能嗅探列名，将每一行转换为 StandardReceiptItem。

列名嗅探策略（两轮）：
  1. 精确匹配预定义候选列名列表
  2. 大小写不敏感子串模糊匹配
  若日期列或金额列均找不到，抛 ValueError（调用方返回 422）。

行过滤规则：
  - 全空行（pandas dropna(how='all')）直接忽略
  - 日期无法解析 → 跳过，记录 skipped
  - 金额 ≤ 0 或无法解析 → 跳过，记录 skipped
  - summary/counterparty 缺失时用兜底值（"批量导入"）
"""
import io
import logging
from datetime import date

from fastapi import UploadFile

from schemas.batch_schemas import StandardReceiptItem

logger = logging.getLogger(__name__)

# ── 候选列名（精确匹配优先）────────────────────────────────────────────────────
_DATE_COLS    = ["日期", "交易日期", "凭证日期", "票据日期", "date", "Date", "DATE"]
_AMOUNT_COLS  = ["金额", "交易金额", "发生额", "价税合计", "总金额", "税后金额",
                 "amount", "Amount", "AMOUNT"]
_PARTY_COLS   = ["对方单位", "供应商", "客户名称", "对手方", "付款方", "收款方",
                 "counterparty", "Counterparty", "vendor", "Vendor"]
_SUMMARY_COLS = ["摘要", "备注", "说明", "用途", "品名", "业务摘要", "交易摘要",
                 "summary", "Summary", "description", "Description"]


async def parse_excel(file: UploadFile) -> list[StandardReceiptItem]:
    """
    解析 .xlsx / .xls / .csv 上传文件 → StandardReceiptItem 列表。

    参数：
      file — FastAPI UploadFile 对象

    返回：
      有效 StandardReceiptItem 列表（空行/无效行已过滤）

    异常：
      ValueError — 必要列（日期/金额）找不到，或文件格式无法识别
    """
    import pandas as pd

    content  = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".csv"):
        df = _read_csv(content, pd)
    else:
        df = _read_excel(content, pd)

    df = df.dropna(how="all")
    headers = list(df.columns)

    col_date    = _find_col(headers, _DATE_COLS)
    col_amount  = _find_col(headers, _AMOUNT_COLS)
    col_party   = _find_col(headers, _PARTY_COLS)
    col_summary = _find_col(headers, _SUMMARY_COLS)

    if col_date is None or col_amount is None:
        raise ValueError(
            f"找不到必要列（日期 / 金额）。文件列名：{headers}。"
            "请确认表头含"日期"和"金额"字样（或英文 date / amount）。"
        )

    items: list[StandardReceiptItem] = []
    skipped = 0

    for _, row in df.iterrows():
        parsed_date = _parse_date(row.get(col_date), pd)
        if parsed_date is None:
            skipped += 1
            continue

        amount = _parse_amount(row.get(col_amount))
        if amount is None or amount <= 0:
            skipped += 1
            continue

        counterparty = _clean_str(row.get(col_party)) if col_party else None
        summary_raw  = _clean_str(row.get(col_summary)) if col_summary else None
        summary      = summary_raw or counterparty or "批量导入"

        items.append(StandardReceiptItem(
            date         = parsed_date,
            amount       = round(amount, 2),
            counterparty = counterparty,
            summary      = summary,
        ))

    logger.info(
        "Excel 解析完成: %d 条有效记录，%d 行跳过（文件: %s）",
        len(items), skipped, file.filename,
    )
    return items


# ── 内部辅助 ──────────────────────────────────────────────────────────────────

def _read_csv(content: bytes, pd) -> "pd.DataFrame":
    for enc in ("utf-8-sig", "gbk", "gb2312", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(content), encoding=enc)
        except (UnicodeDecodeError, Exception):
            continue
    raise ValueError("CSV 编码无法识别，请将文件另存为 UTF-8（带 BOM）格式后重试。")


def _read_excel(content: bytes, pd) -> "pd.DataFrame":
    try:
        return pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise ValueError(f"Excel 文件解析失败: {exc}") from exc


def _find_col(headers: list[str], candidates: list[str]) -> str | None:
    """先精确匹配，再大小写不敏感子串匹配。"""
    for c in candidates:
        if c in headers:
            return c
    for h in headers:
        for c in candidates:
            if c.lower() in str(h).lower():
                return h
    return None


def _parse_date(raw, pd) -> date | None:
    if raw is None:
        return None
    try:
        if pd.isna(raw):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(raw, date):
        return raw
    try:
        return pd.to_datetime(str(raw)).date()
    except Exception:
        return None


def _parse_amount(raw) -> float | None:
    if raw is None:
        return None
    try:
        cleaned = (
            str(raw)
            .replace(",", "").replace("，", "")
            .replace(" ", "").replace("¥", "").replace("￥", "")
        )
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _clean_str(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return None if s.lower() in ("", "nan", "none", "null") else s
