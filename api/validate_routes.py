"""
报表验证 API（仅用于开发测试）

POST /api/validate/trial-balance
  接收科目余额表 Excel（必填）+ 参考资产负债表/利润表 Excel（可选）
  返回计算结果 + 自动差异对比。
"""
import logging
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from services.validation_service import (
    parse_trial_balance,
    compute_bs_from_trial_balance,
    compute_is_from_trial_balance,
    parse_reference_file,
    compute_bs_diff,
    compute_is_diff,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/validate", tags=["validate"])


async def _read_optional_file(f: Optional[UploadFile]) -> bytes | None:
    if f is None or not f.filename:
        return None
    return await f.read()


@router.post("/trial-balance")
async def validate_from_trial_balance(
    file:     UploadFile          = File(...),
    bs_ref:   Optional[UploadFile] = File(None),
    is_ref:   Optional[UploadFile] = File(None),
    standard: str                  = Form("xiye"),
):
    """
    上传科目余额表 Excel → 返回计算出的资产负债表和利润表。
    可选上传参考资产负债表 / 利润表 Excel → 自动逐行对比差异。
    开发测试用途，不需要鉴权。
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
