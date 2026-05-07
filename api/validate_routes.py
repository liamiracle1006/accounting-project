"""
报表验证 API（仅用于开发测试）

POST /api/validate/trial-balance
  接收科目余额表 Excel（必填）+ 参考资产负债表/利润表 Excel（可选）
  返回计算结果 + 自动差异对比。

POST /api/validate/from-vouchers
  接收上期期末科目表（基准）+ 日期范围 + 可选参考报表
  从已过账凭证聚合本期发生额，计算本期 BS/IS。
"""
import logging
from dataclasses import asdict
from datetime import date as date_t
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from database.connection import get_db
from models.user_account import UserAccount
from services.auth_service import get_current_user
from services.validation_service import (
    parse_trial_balance,
    compute_bs_from_trial_balance,
    compute_is_from_trial_balance,
    parse_reference_file,
    compute_bs_diff,
    compute_is_diff,
    merge_yearly_and_monthly,
    compute_from_baseline_and_vouchers,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/validate", tags=["validate"])


async def _read_optional_file(f: Optional[UploadFile]) -> bytes | None:
    if f is None or not f.filename:
        return None
    return await f.read()


@router.post("/trial-balance")
async def validate_from_trial_balance(
    file:        UploadFile           = File(...),
    month_file:  Optional[UploadFile] = File(None),
    bs_ref:      Optional[UploadFile] = File(None),
    is_ref:      Optional[UploadFile] = File(None),
    standard:    str                  = Form("xiye"),
):
    """
    上传科目余额表 Excel → 返回计算出的资产负债表和利润表。

    file:       1-12月年度导出（必填）。提供 BS 期末/年初余额、IS 本年累计发生额。
    month_file: 单月（如 12 月）导出（可选）。提供 IS 当月发生额。
                若不上传，本月金额列 = 主文件的本期发生额（通常等于全年）。
    bs_ref / is_ref: 参考报表，用于差异对比。
    """
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="请上传 .xlsx 或 .xls 文件")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件不能超过 10MB")

    try:
        parsed = parse_trial_balance(content, standard=standard)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("解析科目余额表失败")
        raise HTTPException(status_code=500, detail=f"解析失败：{exc}")

    # 可选：合并月度文件作为本期发生额来源
    if month_file is not None and month_file.filename:
        if not month_file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(status_code=400, detail="单月文件必须为 .xlsx 或 .xls")
        month_content = await month_file.read()
        if len(month_content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="单月文件不能超过 10MB")
        try:
            month_parsed = parse_trial_balance(month_content, standard=standard)
            parsed = merge_yearly_and_monthly(parsed, month_parsed)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"单月文件解析失败：{exc}")
        except Exception as exc:
            logger.exception("解析单月余额表失败")
            raise HTTPException(status_code=500, detail=f"单月文件解析失败：{exc}")

    try:
        bs  = compute_bs_from_trial_balance(parsed, standard=standard)
        is_ = compute_is_from_trial_balance(parsed, standard=standard)
    except Exception as exc:
        logger.exception("计算报表失败")
        raise HTTPException(status_code=500, detail=f"计算失败：{exc}")

    # 可选：解析参考文件并计算差异
    bs_diff_rows: list[dict] = []
    is_diff_rows: list[dict] = []

    bs_ref_bytes = await _read_optional_file(bs_ref)
    if bs_ref_bytes:
        try:
            ref_pairs   = parse_reference_file(bs_ref_bytes)
            bs_diff_rows = compute_bs_diff(bs, ref_pairs)
        except Exception as exc:
            logger.warning("解析参考资产负债表失败: %s", exc)

    is_ref_bytes = await _read_optional_file(is_ref)
    if is_ref_bytes:
        try:
            ref_pairs   = parse_reference_file(is_ref_bytes)
            is_diff_rows = compute_is_diff(is_, ref_pairs)
        except Exception as exc:
            logger.warning("解析参考利润表失败: %s", exc)

    return {
        "balance_sheet":    asdict(bs),
        "income_statement": asdict(is_),
        "parsed_row_count": parsed["row_count"],
        "column_mapping":   parsed["column_mapping"],
        "bs_diff":          bs_diff_rows,
        "is_diff":          is_diff_rows,
    }


# ── 模式 B：基于"基准余额 + 系统凭证"反推 BS/IS ────────────────────────────────

def _resolve_account_set(db: Session, user: UserAccount) -> int:
    """从用户 tenant_id 查 account_set_id（绕开 ContextVar，与 daybook_routes 一致）"""
    row = db.execute(
        text("SELECT account_set_id FROM account_set WHERE tenant_id = :tid LIMIT 1"),
        {"tid": user.tenant_id},
    ).first()
    if not row:
        raise HTTPException(status_code=400, detail=f"租户 {user.tenant_id} 未找到任何账套")
    return row[0]


@router.post("/from-vouchers")
async def validate_from_vouchers(
    baseline_file: UploadFile = File(..., description="上期期末科目表 Excel"),
    date_from:     str        = Form(..., description="本期起始日 YYYY-MM-DD"),
    date_to:       str        = Form(..., description="本期截止日 YYYY-MM-DD"),
    bs_ref:        Optional[UploadFile] = File(None),
    is_ref:        Optional[UploadFile] = File(None),
    standard:      str        = Form("xiye"),
    current_user:  UserAccount = Depends(get_current_user),
    db:            Session     = Depends(get_db),
):
    """
    用"上期期末科目表（基准）+ 本期 POSTED 凭证"反推本期资产负债表 / 利润表。

    工作流：
    1. 解析 baseline_file → 拿到上期期末（=本期期初）+ 上期 YTD
    2. 从 voucher_line+voucher_header 聚合 [date_from, date_to] 期间 POSTED 凭证发生额
    3. 期末余额 = 期初 + 本期净发生
    4. 复用现有 BS/IS 映射逻辑，并跟参考报表 diff 对比
    """
    # 校验日期
    try:
        df = date_t.fromisoformat(date_from)
        dt = date_t.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式应为 YYYY-MM-DD")
    if df > dt:
        raise HTTPException(status_code=422, detail="date_from 不能晚于 date_to")

    # 校验基准文件
    if not baseline_file.filename or not baseline_file.filename.lower().endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="基准文件请上传 .xlsx / .xls")
    baseline_bytes = await baseline_file.read()
    if len(baseline_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="基准文件不能超过 10MB")

    # 解析基准
    try:
        baseline_parsed = parse_trial_balance(baseline_bytes, standard=standard)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"基准文件解析失败：{exc}")
    except Exception as exc:
        logger.exception("解析基准科目表失败")
        raise HTTPException(status_code=500, detail=f"基准解析失败：{exc}")

    # 解析租户 + 账套
    tenant_id      = current_user.tenant_id
    account_set_id = _resolve_account_set(db, current_user)

    # 用基准 + 本期凭证组装出兼容 parse_trial_balance 输出的 dict
    try:
        derived = compute_from_baseline_and_vouchers(
            db,
            baseline_parsed = baseline_parsed,
            date_from       = df,
            date_to         = dt,
            tenant_id       = tenant_id,
            account_set_id  = account_set_id,
            standard        = standard,
        )
    except Exception as exc:
        logger.exception("聚合凭证失败")
        raise HTTPException(status_code=500, detail=f"聚合凭证失败：{exc}")

    # 复用现有 BS/IS 计算
    try:
        bs  = compute_bs_from_trial_balance(derived, standard=standard)
        is_ = compute_is_from_trial_balance(derived, standard=standard)
    except Exception as exc:
        logger.exception("计算报表失败")
        raise HTTPException(status_code=500, detail=f"计算失败：{exc}")

    # 可选参考文件 diff
    bs_diff_rows: list[dict] = []
    is_diff_rows: list[dict] = []

    bs_ref_bytes = await _read_optional_file(bs_ref)
    if bs_ref_bytes:
        try:
            ref_pairs    = parse_reference_file(bs_ref_bytes)
            bs_diff_rows = compute_bs_diff(bs, ref_pairs)
        except Exception as exc:
            logger.warning("解析参考资产负债表失败: %s", exc)

    is_ref_bytes = await _read_optional_file(is_ref)
    if is_ref_bytes:
        try:
            ref_pairs    = parse_reference_file(is_ref_bytes)
            is_diff_rows = compute_is_diff(is_, ref_pairs)
        except Exception as exc:
            logger.warning("解析参考利润表失败: %s", exc)

    # 凭证统计（透明度信息：让用户知道聚合了多少条凭证）
    voucher_count = db.execute(text("""
        SELECT COUNT(*) FROM voucher_header
        WHERE tenant_id = :tid AND account_set_id = :asid
          AND review_status = 'POSTED'
          AND voucher_date >= :df AND voucher_date <= :dt
    """), {
        "tid": tenant_id, "asid": account_set_id, "df": df, "dt": dt,
    }).scalar() or 0

    return {
        "balance_sheet":    asdict(bs),
        "income_statement": asdict(is_),
        "voucher_count":    voucher_count,
        "date_from":        str(df),
        "date_to":          str(dt),
        "baseline_row_count": baseline_parsed["row_count"],
        "column_mapping":   baseline_parsed["column_mapping"],
        "bs_diff":          bs_diff_rows,
        "is_diff":          is_diff_rows,
    }
