# -*- coding: utf-8 -*-
"""
序时账（流水明细）Excel 导入服务

接受一份序时账 Excel（每行 = 一条借/贷分录，多行同凭证号合并单元格），
解析后按凭证号分组，生成 OperationalRecord + VoucherHeader + VoucherLine 三联结构，
所有凭证统一进 DRAFT 状态等待人工审核。

Excel 格式假设（小企业准则）：
| 日期 | 凭证号 | 摘要 | 科目编码 | 科目名称 | 借方金额 | 贷方金额 | 制单人 | 审核人 | 附件数 | 备注 |
- 同凭证号的多行借/贷在 日期/凭证号/摘要 列存在合并单元格
- 凭证号格式 "记-N"（凭证字 + 序号）
- 科目码可能为 4-10 位（子科目），统一归一到 4 位母科目码 + GAAP 标准化
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from models.operational_record import OperationalRecord, RecordStatus
from models.voucher_header import VoucherReviewStatus
from models.voucher_line import VoucherLine
from services.validation_service import _resolve_code, _to_decimal

logger = logging.getLogger(__name__)

# ── 列名识别（关键词列表，从最常见到最少见排列）──────────────────────────────────
_COL_PATTERNS: dict[str, list[str]] = {
    "date":        ["日期", "凭证日期", "记账日期"],
    "voucher_no":  ["凭证号", "凭证编号", "号数"],
    "memo":        ["摘要", "凭证摘要", "业务说明"],
    "subject_code":["科目编码", "科目代码", "科目编号", "编码"],
    "subject_name":["科目名称", "科目"],
    "debit":       ["借方金额", "借方", "借方发生额"],
    "credit":      ["贷方金额", "贷方", "贷方发生额"],
}

# 凭证字+序号 拆分正则："记-1" / "记 1" / "转-25" 都匹配
_VOUCHER_NO_RE = re.compile(r"^([一-龥A-Za-z]+)\s*[-_\s]?\s*(\d+)\s*$")


@dataclass
class DaybookImportError:
    """单张凭证解析/入库失败的记录"""
    voucher_no: str
    reason:     str
    rows:       list[dict] = field(default_factory=list)


@dataclass
class DaybookImportResult:
    """整个导入任务的汇总结果"""
    total_rows:       int
    parsed_vouchers:  int
    created_vouchers: int
    errors:           list[DaybookImportError] = field(default_factory=list)
    column_mapping:   dict[str, str] = field(default_factory=dict)


# ── 辅助函数 ────────────────────────────────────────────────────────────────────

def _detect_columns(df: pd.DataFrame) -> dict[str, str]:
    """根据列名关键词匹配出每个逻辑字段在 DataFrame 中的实际列名。"""
    mapping: dict[str, str] = {}
    cols = [str(c).strip() for c in df.columns]
    for field_name, patterns in _COL_PATTERNS.items():
        for pat in patterns:
            for col in cols:
                if pat in col:
                    mapping[field_name] = col
                    break
            if field_name in mapping:
                break
    return mapping


def _parse_date(val: Any) -> date | None:
    if pd.isna(val):
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _split_voucher_no(s: str) -> tuple[str, int | None]:
    """'记-1' → ('记', 1)；解析失败返回 ('记', None)"""
    if not s:
        return ("记", None)
    m = _VOUCHER_NO_RE.match(s.strip())
    if m:
        return (m.group(1), int(m.group(2)))
    return ("记", None)


def _normalize_subject_code(raw_code: str, name: str) -> str:
    """
    把 10 位子科目码归一到 4 位母科目，再走 _resolve_code 转 GAAP。
    示例：'5401004' → '5401' → '6401'
    """
    if not raw_code:
        return ""
    code4 = str(raw_code).strip()[:4]
    return _resolve_code(code4, name or "")


# ── 主入口 ──────────────────────────────────────────────────────────────────────

def parse_daybook_excel(content: bytes) -> tuple[pd.DataFrame, dict[str, str]]:
    """
    读 Excel + ffill 处理合并单元格 + 列识别。
    返回 (cleaned_df, column_mapping)。
    """
    try:
        df = pd.read_excel(io.BytesIO(content), dtype=object)
    except Exception as exc:
        raise ValueError(f"无法读取 Excel 文件：{exc}")

    if df.empty:
        raise ValueError("Excel 是空的")

    col_map = _detect_columns(df)
    required = ["voucher_no", "subject_code", "debit", "credit"]
    missing  = [k for k in required if k not in col_map]
    if missing:
        raise ValueError(
            f"Excel 缺少必要列（按关键词匹配失败）：{missing}。"
            f"已识别列：{col_map}。请检查表头是否包含'凭证号/科目编码/借方金额/贷方金额'等关键词。"
        )

    # 合并单元格列：日期/凭证号/摘要 用 ffill 填充
    fill_cols = [col_map[k] for k in ("date", "voucher_no", "memo") if k in col_map]
    if fill_cols:
        df[fill_cols] = df[fill_cols].ffill()

    # 凭证号空 + 借贷都空 → 删
    code_col   = col_map["subject_code"]
    debit_col  = col_map["debit"]
    credit_col = col_map["credit"]

    def _row_is_empty(r) -> bool:
        return pd.isna(r[code_col]) and pd.isna(r[debit_col]) and pd.isna(r[credit_col])

    df = df[~df.apply(_row_is_empty, axis=1)].copy()

    return df, col_map


def import_daybook(
    db:             Session,
    content:        bytes,
    tenant_id:      int,
    account_set_id: int,
    standard:       str = "xiye",
) -> DaybookImportResult:
    """
    主入口：解析 + 按凭证号分组 + 入库为 DRAFT。
    每张凭证不平衡或出错则记入 errors，不阻塞其他凭证。
    """
    df, col_map = parse_daybook_excel(content)

    date_col   = col_map.get("date")
    vno_col    = col_map["voucher_no"]
    memo_col   = col_map.get("memo")
    code_col   = col_map["subject_code"]
    name_col   = col_map.get("subject_name")
    debit_col  = col_map["debit"]
    credit_col = col_map["credit"]

    result = DaybookImportResult(
        total_rows      = int(len(df)),
        parsed_vouchers = 0,
        created_vouchers= 0,
        column_mapping  = col_map,
    )

    # 按凭证号分组（保持文件内出现顺序）
    grouped: dict[str, list[dict]] = {}
    for _, r in df.iterrows():
        vno = str(r[vno_col]).strip() if not pd.isna(r[vno_col]) else ""
        if not vno:
            continue
        grouped.setdefault(vno, []).append(r.to_dict())

    result.parsed_vouchers = len(grouped)

    for vno, rows in grouped.items():
        try:
            _create_one_voucher(
                db, vno, rows,
                date_col=date_col, memo_col=memo_col,
                code_col=code_col, name_col=name_col,
                debit_col=debit_col, credit_col=credit_col,
                tenant_id=tenant_id, account_set_id=account_set_id,
            )
            result.created_vouchers += 1
        except Exception as exc:
            db.rollback()
            logger.warning("凭证 %s 导入失败：%s", vno, exc)
            result.errors.append(DaybookImportError(
                voucher_no=vno, reason=str(exc),
                rows=[{k: str(v) for k, v in r.items()} for r in rows[:5]],
            ))

    db.commit()
    return result


def _create_one_voucher(
    db:             Session,
    vno_str:        str,
    rows:           list[dict],
    *,
    date_col:       str | None,
    memo_col:       str | None,
    code_col:       str,
    name_col:       str | None,
    debit_col:      str,
    credit_col:     str,
    tenant_id:      int,
    account_set_id: int,
) -> None:
    """创建一张凭证（OperationalRecord + VoucherHeader + N 条 VoucherLine）。"""

    # 第一行的元数据（合并单元格已 ffill 过，每行都一致）
    head = rows[0]

    # 日期
    voucher_date: date | None = None
    if date_col:
        voucher_date = _parse_date(head.get(date_col))
    if voucher_date is None:
        voucher_date = date.today()

    # 摘要
    memo_text = ""
    if memo_col and not pd.isna(head.get(memo_col)):
        memo_text = str(head.get(memo_col)).strip()[:500]

    # 凭证字 + 序号
    word, number = _split_voucher_no(vno_str)

    # 解析所有分录
    line_specs: list[dict] = []
    total_debit  = Decimal("0")
    total_credit = Decimal("0")

    for r in rows:
        raw_code = str(r.get(code_col, "")).strip() if not pd.isna(r.get(code_col)) else ""
        raw_name = str(r.get(name_col, "")).strip() if name_col and not pd.isna(r.get(name_col)) else ""
        if not raw_code:
            continue

        subject_code = _normalize_subject_code(raw_code, raw_name)
        if not subject_code:
            raise ValueError(f"科目码无法归一：{raw_code} {raw_name}")

        debit_amt  = _to_decimal(r.get(debit_col))
        credit_amt = _to_decimal(r.get(credit_col))

        # line.memo 保留原始子科目信息
        line_memo = f"{raw_code} {raw_name}".strip()[:200]

        # 红字记账规则：负数金额表示反方向
        #   借方 -X = 贷方 +X（如：用户在借方写 -5.20 表示利息收入冲减费用）
        #   贷方 -X = 借方 +X
        if debit_amt < 0:
            credit_amt += (-debit_amt)
            debit_amt = Decimal("0")
        if credit_amt < 0:
            debit_amt += (-credit_amt)
            credit_amt = Decimal("0")

        if debit_amt > 0:
            line_specs.append({
                "subject_code": subject_code,
                "direction":    "DEBIT",
                "amount":       debit_amt,
                "memo":         line_memo,
            })
            total_debit += debit_amt
        if credit_amt > 0:
            line_specs.append({
                "subject_code": subject_code,
                "direction":    "CREDIT",
                "amount":       credit_amt,
                "memo":         line_memo,
            })
            total_credit += credit_amt

    if not line_specs:
        raise ValueError("无有效分录行")

    # 借贷平衡校验
    diff = abs(total_debit - total_credit)
    if diff >= Decimal("0.01"):
        raise ValueError(
            f"借贷不平衡：借方 ¥{total_debit:.2f}，贷方 ¥{total_credit:.2f}，差额 ¥{diff:.2f}"
        )

    # 1. 先创 OperationalRecord（VoucherHeader.record_id 是 NOT NULL）
    record = OperationalRecord(
        tenant_id      = tenant_id,
        account_set_id = account_set_id,
        raw_text       = f"[序时账导入 {vno_str}] {memo_text}" if memo_text else f"[序时账导入 {vno_str}]",
        status         = RecordStatus.PROCESSED,
    )
    db.add(record)
    db.flush()  # 拿到 record_id

    # 2. 创 VoucherHeader（DRAFT 状态）
    # 用原生 SQL 绕开 ORM 模型与实际 DDL 不同步的问题
    # （ORM 有 voucher_number/voucher_word/creator_id/is_deleted，DDL 没有）
    # 凭证字+序号信息写到 memo 头部保留：[记-N] memo_text
    full_memo = f"[{vno_str}] {memo_text}" if memo_text else f"[{vno_str}]"
    full_memo = full_memo[:500]
    result = db.execute(text("""
        INSERT INTO voucher_header
            (tenant_id, account_set_id, record_id, voucher_date,
             total_amount, memo, review_status)
        VALUES
            (:tenant_id, :account_set_id, :record_id, :voucher_date,
             :total_amount, :memo, :review_status)
    """), {
        "tenant_id":      tenant_id,
        "account_set_id": account_set_id,
        "record_id":      record.record_id,
        "voucher_date":   voucher_date,
        "total_amount":   total_debit,
        "memo":           full_memo,
        "review_status":  VoucherReviewStatus.DRAFT,
    })
    voucher_id = result.lastrowid

    # 3. 创 VoucherLine（这张表 ORM 与 DDL 一致，可以用 ORM）
    for spec in line_specs:
        db.add(VoucherLine(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            voucher_id     = voucher_id,
            subject_code   = spec["subject_code"],
            direction      = spec["direction"],
            amount         = spec["amount"],
            memo           = spec["memo"],
        ))
