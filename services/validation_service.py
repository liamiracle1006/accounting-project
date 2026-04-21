"""
ValidationService — 从科目余额表 Excel 计算财务报表（开发测试用）

工作流:
  1. parse_trial_balance(bytes) → 解析 Excel，构建余额字典
  2. compute_bs_from_trial_balance(parsed)  → 调用 _map_balance_sheet
  3. compute_is_from_trial_balance(parsed)  → 调用 _map_income_statement
"""
import io
import re
import logging
from decimal import Decimal, InvalidOperation

import pandas as pd

from services.report_service import (
    _map_balance_sheet,
    _map_income_statement,
    BalanceSheet,
    IncomeStatement,
)

logger = logging.getLogger(__name__)

# 列识别关键词（正则，不区分大小写）
_COL_PATTERNS: dict[str, re.Pattern] = {
    "code":       re.compile(r"科目.*(代码|编码)|代码|编码|code", re.IGNORECASE),
    "beg_debit":  re.compile(r"期初.*(借|借方)|(借|借方).*期初", re.IGNORECASE),
    "beg_credit": re.compile(r"期初.*(贷|贷方)|(贷|贷方).*期初", re.IGNORECASE),
    "cur_debit":  re.compile(r"本期.*(借|借方)|(借|借方).*本期|(发生|累计).*(借|借方)", re.IGNORECASE),
    "cur_credit": re.compile(r"本期.*(贷|贷方)|(贷|贷方).*本期|(发生|累计).*(贷|贷方)", re.IGNORECASE),
    "end_debit":  re.compile(r"期末.*(借|借方)|(借|借方).*期末", re.IGNORECASE),
    "end_credit": re.compile(r"期末.*(贷|贷方)|(贷|贷方).*期末", re.IGNORECASE),
}


def _to_decimal(val) -> Decimal:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return Decimal("0")
    try:
        return Decimal(str(val).replace(",", "").strip() or "0")
    except InvalidOperation:
        return Decimal("0")


def _detect_columns(df: pd.DataFrame) -> dict[str, str] | None:
    """
    尝试将 DataFrame 的列名映射到标准字段。
    返回 {field: col_name} 或 None（若 code + end_debit 或 end_credit 缺失）。
    """
    cols = [str(c) for c in df.columns]
    mapping: dict[str, str] = {}
    for field, pattern in _COL_PATTERNS.items():
        for col in cols:
            if pattern.search(col):
                mapping[field] = col
                break
    if "code" not in mapping:
        return None
    if "end_debit" not in mapping and "end_credit" not in mapping:
        return None
    return mapping


def _try_load_excel(file_bytes: bytes, skiprows: int) -> pd.DataFrame | None:
    try:
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            skiprows=skiprows,
            dtype=str,
        )
        df.columns = [str(c).strip() for c in df.columns]
        return df
    except Exception:
        return None


def parse_trial_balance(file_bytes: bytes) -> dict:
    """
    解析科目余额表 Excel，返回:
    {
      "end_bal":        {code: Decimal},   # 期末余额（借-贷），用于资产负债表
      "beg_bal":        {code: Decimal},   # 期初余额（借-贷），用于资产负债表年初列
      "cur_debit_map":  {code: Decimal},   # 本期借方发生额，用于利润表
      "cur_credit_map": {code: Decimal},   # 本期贷方发生额，用于利润表
      "raw_rows":       list[dict],        # 原始解析行，供前端展示 / debug
      "column_mapping": dict[str, str],    # 识别到的列名映射，供 debug
      "row_count":      int,
    }
    如果列识别失败，抛出 ValueError 并附上当前列名列表。
    """
    col_mapping: dict[str, str] | None = None
    df: pd.DataFrame | None = None

    for skip in range(6):
        df_try = _try_load_excel(file_bytes, skip)
        if df_try is None:
            continue
        mapping = _detect_columns(df_try)
        if mapping is not None:
            col_mapping = mapping
            df = df_try
            break

    if df is None or col_mapping is None:
        # 提供友好的错误信息
        raw_df = _try_load_excel(file_bytes, 0)
        found_cols = list(raw_df.columns) if raw_df is not None else []
        raise ValueError(
            f"无法自动识别科目余额表列名。"
            f"需要包含：科目代码、期末余额借方/贷方、本期发生额借方/贷方、期初余额借方/贷方。"
            f"实际检测到的列名：{found_cols}"
        )

    end_bal:        dict[str, Decimal] = {}
    beg_bal:        dict[str, Decimal] = {}
    cur_debit_map:  dict[str, Decimal] = {}
    cur_credit_map: dict[str, Decimal] = {}
    raw_rows: list[dict] = []

    code_col = col_mapping["code"]
    get = lambda row, field: _to_decimal(row.get(col_mapping.get(field, "__none__")))

    for _, row in df.iterrows():
        raw_code = str(row.get(code_col, "")).strip()
        if not raw_code or raw_code in ("nan", "None", "科目代码", "合计", "总计"):
            continue
        # 只保留纯数字科目代码
        code = re.sub(r"\s+", "", raw_code)
        if not re.match(r"^\d{4,}", code):
            continue

        end_d  = get(row, "end_debit")
        end_c  = get(row, "end_credit")
        beg_d  = get(row, "beg_debit")
        beg_c  = get(row, "beg_credit")
        cur_d  = get(row, "cur_debit")
        cur_c  = get(row, "cur_credit")

        net_end = end_d - end_c
        net_beg = beg_d - beg_c

        if net_end != 0:
            end_bal[code] = end_bal.get(code, Decimal("0")) + net_end
        if net_beg != 0:
            beg_bal[code] = beg_bal.get(code, Decimal("0")) + net_beg
        if cur_d != 0:
            cur_debit_map[code]  = cur_debit_map.get(code, Decimal("0")) + cur_d
        if cur_c != 0:
            cur_credit_map[code] = cur_credit_map.get(code, Decimal("0")) + cur_c

        raw_rows.append({
            "code":       code,
            "end_debit":  float(end_d),
            "end_credit": float(end_c),
            "beg_debit":  float(beg_d),
            "beg_credit": float(beg_c),
            "cur_debit":  float(cur_d),
            "cur_credit": float(cur_c),
        })

    if not raw_rows:
        raise ValueError("解析到 0 条有效科目行，请检查文件格式是否正确。")

    return {
        "end_bal":        end_bal,
        "beg_bal":        beg_bal,
        "cur_debit_map":  cur_debit_map,
        "cur_credit_map": cur_credit_map,
        "raw_rows":       raw_rows,
        "column_mapping": col_mapping,
        "row_count":      len(raw_rows),
    }


def _make_sum_fn(debit_map: dict[str, Decimal], credit_map: dict[str, Decimal]):
    """构造 IS 取数函数：按科目代码前缀聚合发生额（模拟 _sum_period 的 LIKE 行为）"""
    def fn(code_prefix: str, direction: str) -> Decimal:
        lookup = debit_map if direction == "DEBIT" else credit_map
        return sum(
            (v for k, v in lookup.items() if k.startswith(code_prefix)),
            Decimal("0"),
        )
    return fn


def compute_bs_from_trial_balance(parsed: dict) -> BalanceSheet:
    """用期末余额和期初余额计算资产负债表。"""
    return _map_balance_sheet(
        parsed["end_bal"],
        parsed["beg_bal"],
        as_of_str="（来自Excel）",
        beg_of_year_str="（来自Excel期初）",
    )


def compute_is_from_trial_balance(parsed: dict) -> IncomeStatement:
    """用本期发生额计算利润表（无上期对比数据）。"""
    cur_fn  = _make_sum_fn(parsed["cur_debit_map"], parsed["cur_credit_map"])
    prev_fn = _make_sum_fn({}, {})  # 科目余额表无上期数据，上期列为 0
    return _map_income_statement(
        cur_fn, prev_fn,
        date_from_str="（来自Excel）",
        date_to_str="（来自Excel）",
        prev_from_str="N/A",
        prev_to_str="N/A",
    )


# ---------------------------------------------------------------------------
# 参考报表解析与差异对比
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """
    标准化行项目名称，用于模糊匹配。
    "一、营业收入" → "营业收入"，"减：营业成本" → "营业成本"
    """
    s = str(name).strip()
    s = re.sub(r'^[一二三四五六七八九十百]+[、.]\s*', '', s)   # 去掉序号前缀
    s = re.sub(r'^(减：|加：|其中：|（含.*?）)', '', s)         # 去掉借贷前缀
    s = re.sub(r'\s+', '', s)                                    # 去掉所有空白
    return s


def parse_reference_file(file_bytes: bytes) -> dict[str, float]:
    """
    解析参考报表 Excel（资产负债表或利润表），提取 {行项目名称: 数值} 字典。

    兼容两种布局：
    - 利润表：名称列 | 本期金额 | 上期金额（取第一个数值列）
    - 资产负债表：资产名 | 期末 | 年初 || 负债名 | 期末 | 年初（左右双栏）
    """
    SKIP_NAMES = {
        '资产', '负债', '权益', '项目', '科目', '行次',
        '期末余额', '年初余额', '本期金额', '上期金额',
        '流动资产', '非流动资产', '流动负债', '非流动负债',
        '负债合计', '所有者权益', '合计',
    }

    for skip in range(6):
        try:
            df = pd.read_excel(
                io.BytesIO(file_bytes),
                skiprows=skip,
                header=None,
                dtype=str,
            )
            pairs: dict[str, float] = {}

            for _, row in df.iterrows():
                cells = [str(c).strip() for c in row]
                for i, cell in enumerate(cells):
                    if not re.search(r'[一-鿿]', cell):
                        continue
                    clean = re.sub(r'\s+', '', cell)
                    if clean in SKIP_NAMES or len(clean) < 2:
                        continue
                    # 往后最多 4 格找第一个有效数字
                    for j in range(i + 1, min(i + 5, len(cells))):
                        try:
                            num_str = cells[j].replace(',', '').replace('，', '')
                            if num_str in ('nan', 'None', ''):
                                continue
                            val = float(num_str)
                            if clean not in pairs:
                                pairs[clean] = val
                            break
                        except (ValueError, TypeError):
                            continue

            if len(pairs) >= 3:
                return pairs
        except Exception:
            continue

    return {}


def compute_bs_diff(
    bs: BalanceSheet,
    ref_pairs: dict[str, float],
) -> list[dict]:
    """
    对比资产负债表期末余额与参考数据。
    返回已匹配行的差异列表，未匹配行不返回（避免误报）。
    """
    if not ref_pairs:
        return []

    norm_ref = {_normalize_name(k): v for k, v in ref_pairs.items()}
    diffs = []

    for item in bs.assets + bs.liabilities + bs.equity:
        norm = _normalize_name(item.name)
        ref_val = norm_ref.get(norm)
        if ref_val is None:
            continue
        computed = float(item.end_bal)
        diff = round(computed - ref_val, 2)
        diffs.append({
            "name":     item.name,
            "computed": computed,
            "reference": ref_val,
            "diff":     diff,
            "match":    abs(diff) < 1.0,
        })

    return diffs


def compute_is_diff(
    is_: IncomeStatement,
    ref_pairs: dict[str, float],
) -> list[dict]:
    """对比利润表本期金额与参考数据。"""
    if not ref_pairs:
        return []

    norm_ref = {_normalize_name(k): v for k, v in ref_pairs.items()}
    diffs = []

    for item in is_.items:
        norm = _normalize_name(item.name)
        ref_val = norm_ref.get(norm)
        if ref_val is None:
            continue
        computed = float(item.cur_amt)
        diff = round(computed - ref_val, 2)
        diffs.append({
            "name":      item.name,
            "computed":  computed,
            "reference": ref_val,
            "diff":      diff,
            "match":     abs(diff) < 1.0,
        })

    return diffs
