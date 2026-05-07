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
    _map_balance_sheet_xiye,
    _map_income_statement,
    _map_income_statement_xiye,
    BalanceSheet,
    IncomeStatement,
)

logger = logging.getLogger(__name__)

# 列识别关键词（正则，不区分大小写）
_COL_PATTERNS: dict[str, re.Pattern] = {
    "code":       re.compile(r"科目.*(代码|编码)|代码|编码|code", re.IGNORECASE),
    "name":       re.compile(r"科目.*名称|名称|subject.*name", re.IGNORECASE),
    "beg_debit":  re.compile(r"期初.*(借|借方)|(借|借方).*期初", re.IGNORECASE),
    "beg_credit": re.compile(r"期初.*(贷|贷方)|(贷|贷方).*期初", re.IGNORECASE),
    # 本期发生额（单月）
    "cur_debit":  re.compile(r"本期.*(借|借方)|(借|借方).*本期", re.IGNORECASE),
    "cur_credit": re.compile(r"本期.*(贷|贷方)|(贷|贷方).*本期", re.IGNORECASE),
    # 本年累计发生额（年累计，优先用于利润表）
    "ytd_debit":  re.compile(r"本年累计.*(借|借方)|(累计发生).*(借|借方)", re.IGNORECASE),
    "ytd_credit": re.compile(r"本年累计.*(贷|贷方)|(累计发生).*(贷|贷方)", re.IGNORECASE),
    "end_debit":  re.compile(r"期末.*(借|借方)|(借|借方).*期末", re.IGNORECASE),
    "end_credit": re.compile(r"期末.*(贷|贷方)|(贷|贷方).*期末", re.IGNORECASE),
}

# 科目名称前缀剥离（用于IS明细行名称匹配）
# 余额表里是"应交城市维护建设税"，利润表模板是"城市维护建设税"，去掉前缀后才能匹配
_STRIP_NAME_PREFIX = re.compile(r"^(应交|应缴|预交|代交|待交)")

# IS 明细行 → 候选名称关键词（去掉前缀后做 substring 匹配）
_IS_DETAIL_KEYWORDS: dict[int, list[str]] = {
    4:  ["消费税"],
    5:  ["营业税"],
    6:  ["城市维护建设税", "城建税"],
    7:  ["资源税"],
    8:  ["土地增值税"],
    9:  ["城镇土地使用税", "房产税", "车船税", "印花税"],
    10: ["教育费附加", "矿产资源补偿费", "排污费"],
    12: ["商品维修费"],
    13: ["广告费", "业务宣传费"],
    15: ["开办费"],
    16: ["业务招待费"],
    17: ["研究费用", "研发费用"],
    19: ["利息费用", "利息支出", "利息净支出"],
    23: ["政府补助"],
    25: ["坏账损失"],
    29: ["税收滞纳金", "滞纳金"],
}

# 走借方字典回填的 row（费用科目下的明细，金额在借方而非贷方）
_IS_DETAIL_DEBIT_ROWS: set[int] = {15, 16, 17, 19, 25, 29}

# ── 科目编码规范化（多版本会计制度兼容）──────────────────────────────────────
# 科目名称 → 企业会计准则2006标准编码（名称跨制度稳定，优先于编码规则）
_ACCOUNT_NAME_TO_CODE: dict[str, str] = {
    # 损益类 → 6xxx
    "主营业务收入": "6001", "营业收入": "6001", "主营业务销售收入": "6001",
    "其他业务收入": "6051",
    "投资收益": "6111",
    "营业外收入": "6301",
    "主营业务成本": "6401", "营业成本": "6401",
    "其他业务成本": "6402",
    "营业税金及附加": "6403", "税金及附加": "6403",
    "销售费用": "6601", "营业费用": "6601",
    "管理费用": "6602",
    "财务费用": "6603",
    "研发费用": "6604",
    "营业外支出": "6711",
    "所得税费用": "6801",
    # 权益类 → 4xxx（小企业制度3xxx → 新准则4xxx）
    "实收资本": "4001",
    "资本公积": "4002",
    "盈余公积": "4101",
    "本年利润": "4103",
    "利润分配": "4104", "未分配利润": "4104",
    # 企业准则特有损益科目
    "公允价值变动损益": "6101",
    "资产减值损失": "6701",
    "以前年度损益调整": "6901",
    # 资产：累计摊销（老制度1702，新准则在1703）
    "累计摊销": "1703",
}

# 编码前缀兜底：仅处理权益类3xxx→4xxx（两套准则3xxx均为权益，无冲突）
# 损益类5xxx不做前缀映射，完全依赖名称匹配，避免与企业准则的5xxx成本类冲突
_LEGACY_PREFIX_MAP: dict[str, str] = {
    "3001": "4001", "3002": "4002", "3101": "4101", "3103": "4103", "3104": "4104",
}


def _resolve_code(raw_code: str, account_name: str) -> str:
    """
    将任意会计制度的科目编码规范化为企业会计准则2006标准编码。
    优先级：名称精确匹配 > 名称前缀匹配（子科目）> 编码前缀兜底 > 原编码不变。
    """
    name = re.sub(r"\s+", "", account_name)
    # 1. 精确名称匹配
    if name in _ACCOUNT_NAME_TO_CODE:
        return _ACCOUNT_NAME_TO_CODE[name]
    # 2. 名称前缀匹配（子科目，如"财务费用-利息费用"→ 归入6603桶）
    for std_name, std_code in _ACCOUNT_NAME_TO_CODE.items():
        if name.startswith(std_name + "-") or name.startswith(std_name + "—"):
            return std_code
    # 3. 编码前缀兜底（处理子科目，如5603001→6603001）
    for legacy, standard in _LEGACY_PREFIX_MAP.items():
        if raw_code.startswith(legacy):
            return standard + raw_code[len(legacy):]
    return raw_code


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


def _try_load_excel_multiheader(file_bytes: bytes, skiprows: int) -> pd.DataFrame | None:
    """读取双行列头格式（如荆鹏等软件导出的科目余额表）。"""
    try:
        df = pd.read_excel(
            io.BytesIO(file_bytes),
            skiprows=skiprows,
            header=[0, 1],
            dtype=str,
        )
        new_cols = []
        for col in df.columns:
            if isinstance(col, tuple):
                parts = [str(p).strip() for p in col
                         if str(p).strip() not in ('nan', 'None', '')]
                new_cols.append(''.join(parts))
            else:
                new_cols.append(str(col).strip())
        df.columns = new_cols
        return df
    except Exception:
        return None


def _find_header_row(file_bytes: bytes) -> int | None:
    """扫描前 30 行，找到包含科目代码列头的行号。"""
    header_hint = re.compile(r"科目.*(代码|编码)|代码|编码|期末|期初|本期")
    try:
        raw = pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str, nrows=30)
        for i, row in raw.iterrows():
            cells = [str(c).strip() for c in row if pd.notna(c)]
            matches = sum(1 for c in cells if header_hint.search(c))
            if matches >= 2:
                return int(i)
    except Exception:
        pass
    return None


def parse_trial_balance(file_bytes: bytes, standard: str = "xiye") -> dict:
    """
    解析科目余额表 Excel，返回余额字典。
    standard: "xiye"（小企业准则，默认）或 "gaap"（企业准则）。
    xiye 模式下将 5xxx/3xxx 科目通过名称映射规范化为 6xxx/4xxx。
    gaap 模式下跳过规范化（编码已是标准格式）。
    """
    col_mapping: dict[str, str] | None = None
    df: pd.DataFrame | None = None

    # 先用智能扫描找到列头行，再按固定范围兜底
    header_row = _find_header_row(file_bytes)
    skip_candidates = list(dict.fromkeys(
        ([header_row] if header_row is not None else []) + list(range(15))
    ))

    for skip in skip_candidates:
        # Try single-header format
        df_try = _try_load_excel(file_bytes, skip)
        if df_try is not None:
            mapping = _detect_columns(df_try)
            if mapping is not None:
                col_mapping = mapping
                df = df_try
                break

        # Try double-row merged-cell header format (e.g. 荆鹏/HBJP export)
        df_try = _try_load_excel_multiheader(file_bytes, skip)
        if df_try is not None:
            mapping = _detect_columns(df_try)
            if mapping is not None:
                col_mapping = mapping
                df = df_try
                break

    if df is None or col_mapping is None:
        raw_df = _try_load_excel(file_bytes, 0)
        found_cols = list(raw_df.columns) if raw_df is not None else []
        raise ValueError(
            f"无法自动识别科目余额表列名。"
            f"需要包含：科目代码、期末余额借方/贷方、本期发生额借方/贷方、期初余额借方/贷方。"
            f"实际检测到的列名：{found_cols}"
        )

    code_col = col_mapping["code"]
    name_col = col_mapping.get("name", "__none__")
    get = lambda row, field: _to_decimal(row.get(col_mapping.get(field, "__none__")))

    # ── 第一步：全量读入原始字典（raw_code 为 key，不做编码规范化）──────────────
    raw_data: dict[str, dict] = {}
    for _, row in df.iterrows():
        raw_code = re.sub(r"\s+", "", str(row.get(code_col, "")).strip())
        if not raw_code or raw_code in ("nan", "None", "科目代码", "合计", "总计"):
            continue
        if not re.match(r"^\d{4,}", raw_code):
            continue
        raw_data[raw_code] = {
            "name": str(row.get(name_col, "")).strip(),
            "ed": get(row, "end_debit"),  "ec": get(row, "end_credit"),
            "bd": get(row, "beg_debit"),  "bc": get(row, "beg_credit"),
            "cd": get(row, "cur_debit"),  "cc": get(row, "cur_credit"),
            "yd": get(row, "ytd_debit"),  "yc": get(row, "ytd_credit"),
        }

    # ── 第1.5步：构建名称→ytd/cur 借/贷方映射（去重前，保留子科目级别名称） ──────────
    # 贷方：用于税金附加等明细回填（如"应交城建税"贷方 → IS城建税行）
    # 借方：用于费用类明细回填（如"利息费用"借方 → IS利息费用行）
    name_ytd_credit: dict[str, Decimal] = {}
    name_cur_credit: dict[str, Decimal] = {}
    name_ytd_debit:  dict[str, Decimal] = {}
    name_cur_debit:  dict[str, Decimal] = {}
    for d in raw_data.values():
        raw_name = re.sub(r"\s+", "", d["name"])
        clean_name = _STRIP_NAME_PREFIX.sub("", raw_name)
        if d["yc"]:
            name_ytd_credit[clean_name] = name_ytd_credit.get(clean_name, Decimal("0")) + d["yc"]
        if d["cc"]:
            name_cur_credit[clean_name] = name_cur_credit.get(clean_name, Decimal("0")) + d["cc"]
        if d["yd"]:
            name_ytd_debit[clean_name]  = name_ytd_debit.get(clean_name,  Decimal("0")) + d["yd"]
        if d["cd"]:
            name_cur_debit[clean_name]  = name_cur_debit.get(clean_name,  Decimal("0")) + d["cd"]

    # ── 第二步：去重清洗————删除父科目存在且有数据时的子科目行 ──────────────────
    # 荆鹏同时导出父行和子行时会造成重复计数。
    # 对于 BS 账户：期末余额非零即可判断父行为汇总行。
    # 对于 IS 账户：月结后期末=0，但本年累计(ytd)有数据 → 也需过滤子行。
    parent_nonzero = {
        code for code, d in raw_data.items()
        if len(code) == 4 and (
            d["ed"] - d["ec"] != 0  # 期末余额非零（BS账户）
            or d["yd"]              # ytd借方非零（IS账户关账后期末=0但ytd有数）
            or d["yc"]              # ytd贷方非零
        )
    }
    raw_data = {
        code: d for code, d in raw_data.items()
        if not (len(code) > 4 and code[:4] in parent_nonzero)
    }

    # ── 第三步：规范化编码并构建余额映射 ─────────────────────────────────────────
    end_bal:        dict[str, Decimal] = {}
    beg_bal:        dict[str, Decimal] = {}
    cur_debit_map:  dict[str, Decimal] = {}
    cur_credit_map: dict[str, Decimal] = {}
    ytd_debit_map:  dict[str, Decimal] = {}
    ytd_credit_map: dict[str, Decimal] = {}
    raw_rows: list[dict] = []

    for raw_code, d in raw_data.items():
        code = _resolve_code(raw_code, d["name"]) if standard == "xiye" else raw_code
        net_end = d["ed"] - d["ec"]
        net_beg = d["bd"] - d["bc"]
        if net_end != 0:
            end_bal[code]        = end_bal.get(code, Decimal("0"))        + net_end
        if net_beg != 0:
            beg_bal[code]        = beg_bal.get(code, Decimal("0"))        + net_beg
        if d["cd"]:
            cur_debit_map[code]  = cur_debit_map.get(code, Decimal("0"))  + d["cd"]
        if d["cc"]:
            cur_credit_map[code] = cur_credit_map.get(code, Decimal("0")) + d["cc"]
        if d["yd"]:
            ytd_debit_map[code]  = ytd_debit_map.get(code, Decimal("0"))  + d["yd"]
        if d["yc"]:
            ytd_credit_map[code] = ytd_credit_map.get(code, Decimal("0")) + d["yc"]
        raw_rows.append({
            "code":       code,
            "end_debit":  float(d["ed"]), "end_credit": float(d["ec"]),
            "beg_debit":  float(d["bd"]), "beg_credit": float(d["bc"]),
            "cur_debit":  float(d["cd"]), "cur_credit": float(d["cc"]),
            "ytd_debit":  float(d["yd"]), "ytd_credit": float(d["yc"]),
        })

    if not raw_rows:
        raise ValueError("解析到 0 条有效科目行，请检查文件格式是否正确。")

    return {
        "end_bal":         end_bal,
        "beg_bal":         beg_bal,
        "cur_debit_map":   cur_debit_map,
        "cur_credit_map":  cur_credit_map,
        "ytd_debit_map":   ytd_debit_map,
        "ytd_credit_map":  ytd_credit_map,
        "name_ytd_credit": name_ytd_credit,
        "name_cur_credit": name_cur_credit,
        "name_ytd_debit":  name_ytd_debit,
        "name_cur_debit":  name_cur_debit,
        "raw_rows":        raw_rows,
        "column_mapping":  col_mapping,
        "row_count":       len(raw_rows),
    }


def _make_sum_fn(debit_map: dict[str, Decimal], credit_map: dict[str, Decimal]):
    """GAAP 模式 IS 取数：按前缀在单方向 map 里聚合。"""
    def fn(code_prefix: str, direction: str) -> Decimal:
        lookup = debit_map if direction == "DEBIT" else credit_map
        return sum((v for k, v in lookup.items() if k.startswith(code_prefix)), Decimal("0"))
    return fn


def _make_xiye_fn(debit_map: dict[str, Decimal], credit_map: dict[str, Decimal]):
    """
    xiye 模式 IS 取数：单方向聚合，同时查 5xxx 和 6xxx 前缀。
    不做净额处理（避免关账分录抵消实际发生额）。
    """
    def fn(code_prefix: str, direction: str) -> Decimal:
        lookup = debit_map if direction == "DEBIT" else credit_map
        prefixes = [code_prefix]
        if code_prefix.startswith("6"):
            prefixes.append("5" + code_prefix[1:])
        elif code_prefix.startswith("5"):
            prefixes.append("6" + code_prefix[1:])
        return sum(
            (v for k, v in lookup.items() if any(k.startswith(p) for p in prefixes)),
            Decimal("0"),
        )
    return fn


def _aggregate_sub_codes(bal: dict[str, Decimal]) -> dict[str, Decimal]:
    """
    将只有子科目（>4位）的余额汇总到4位父科目。
    若4位父科目已有直接余额行（荆鹏同时导出了父行），则不重复汇总。
    解决荆鹏等软件只导出明细子科目、不含合计父行的情况（如应付账款220200→2202）。
    """
    existing4 = {c for c in bal if len(c) == 4}
    result = dict(bal)
    for code, amount in bal.items():
        if len(code) > 4:
            parent4 = code[:4]
            if parent4 not in existing4:
                result[parent4] = result.get(parent4, Decimal("0")) + amount
    return result


def compute_bs_from_trial_balance(parsed: dict, standard: str = "xiye") -> BalanceSheet:
    """用期末余额和年初余额计算资产负债表。standard: "xiye" 小企业准则，"gaap" 企业准则。"""
    end_bal_raw = parsed["end_bal"]
    ytd_d = parsed.get("ytd_debit_map", {})
    ytd_c = parsed.get("ytd_credit_map", {})

    # 年初余额 = 期末余额 - 本年累计净发生额（比直接用期初余额更准确）
    # 公式：年初净余额 = 期末净余额 - (本年累计借方 - 本年累计贷方)
    if ytd_d or ytd_c:
        all_codes = set(list(end_bal_raw.keys()) + list(ytd_d.keys()) + list(ytd_c.keys()))
        beg_bal_raw: dict[str, Decimal] = {}
        for code in all_codes:
            val = (end_bal_raw.get(code, Decimal("0"))
                   - ytd_d.get(code, Decimal("0"))
                   + ytd_c.get(code, Decimal("0")))
            if val != Decimal("0"):
                beg_bal_raw[code] = val
    else:
        beg_bal_raw = parsed["beg_bal"]  # 无本年累计列时降级使用期初余额

    # 子科目汇总到4位父科目（处理荆鹏等只导出子科目不含父行的情况）
    end_bal = _aggregate_sub_codes(end_bal_raw)
    beg_bal = _aggregate_sub_codes(beg_bal_raw)

    if standard == "xiye":
        return _map_balance_sheet_xiye(end_bal, beg_bal,
                                       as_of_str="（来自Excel）",
                                       beg_of_year_str="（来自Excel年初）")
    return _map_balance_sheet(end_bal, beg_bal,
                              as_of_str="（来自Excel）",
                              beg_of_year_str="（来自Excel年初）")


def _merge_maps(ytd: dict, cur: dict) -> dict:
    """每个科目优先取 ytd，ytd 没有才取 cur（避免 ytd 有 BS 数据但无 IS 数据时 IS 全零）。"""
    merged = dict(cur)
    merged.update(ytd)   # ytd 覆盖 cur
    return merged


def aggregate_voucher_period(
    db,
    tenant_id: int,
    account_set_id: int,
    date_from,
    date_to,
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    """
    聚合 [date_from, date_to] 期间所有 POSTED 凭证的借/贷方发生额（按 subject_code 4 位母科目分组）。
    返回 (cur_debit_map, cur_credit_map)。
    """
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT vl.subject_code, vl.direction, SUM(vl.amount) AS total
        FROM voucher_line vl
        INNER JOIN voucher_header vh ON vh.voucher_id = vl.voucher_id
        WHERE vh.tenant_id = :tid
          AND vh.account_set_id = :asid
          AND vh.review_status = 'POSTED'
          AND vh.voucher_date >= :df
          AND vh.voucher_date <= :dt
        GROUP BY vl.subject_code, vl.direction
    """), {
        "tid": tenant_id, "asid": account_set_id,
        "df":  date_from, "dt":  date_to,
    }).fetchall()

    cur_debit_map: dict[str, Decimal] = {}
    cur_credit_map: dict[str, Decimal] = {}
    for code, direction, total in rows:
        amt = Decimal(str(total))
        if direction == "DEBIT":
            cur_debit_map[code] = amt
        elif direction == "CREDIT":
            cur_credit_map[code] = amt
    return cur_debit_map, cur_credit_map


def compute_from_baseline_and_vouchers(
    db,
    baseline_parsed: dict,
    date_from,
    date_to,
    tenant_id: int,
    account_set_id: int,
    standard: str = "xiye",
) -> dict:
    """
    用"上期期末科目表（基准）+ 本期 POSTED 凭证发生额"反推本期科目表数据。
    返回与 parse_trial_balance() 输出格式兼容的字典，可直接喂给
    compute_bs_from_trial_balance / compute_is_from_trial_balance。

    数学关系：
      本期期末 = 上期期末 + 本期借 - 本期贷
      本期 YTD = 上期 YTD + 本期发生（借/贷各自累加）
      → BS 反推的"年初余额" = 本期期末 - 本期 YTD 净 = 上期期末 - 上期 YTD 净
        = 上期反推出的同一个年初 ✓
    """
    # 1. 上期期末 = 本期期初（净额形式：debit - credit）
    baseline_end_bal = baseline_parsed.get("end_bal", {})

    # 2. 本期 POSTED 凭证聚合
    cur_debit_map, cur_credit_map = aggregate_voucher_period(
        db, tenant_id, account_set_id, date_from, date_to
    )

    # 3. 本期期末（净额）= 上期期末 + 本期净发生
    all_codes = (set(baseline_end_bal.keys())
                 | set(cur_debit_map.keys())
                 | set(cur_credit_map.keys()))
    end_bal: dict[str, Decimal] = {}
    for code in all_codes:
        val = (baseline_end_bal.get(code, Decimal("0"))
               + cur_debit_map.get(code, Decimal("0"))
               - cur_credit_map.get(code, Decimal("0")))
        if val != 0:
            end_bal[code] = val

    # 4. YTD = 上期 YTD（截至上期末的本年累计）+ 本期发生额
    baseline_ytd_d = baseline_parsed.get("ytd_debit_map", {})
    baseline_ytd_c = baseline_parsed.get("ytd_credit_map", {})
    ytd_debit_map: dict[str, Decimal] = dict(baseline_ytd_d)
    ytd_credit_map: dict[str, Decimal] = dict(baseline_ytd_c)
    for code, v in cur_debit_map.items():
        ytd_debit_map[code] = ytd_debit_map.get(code, Decimal("0")) + v
    for code, v in cur_credit_map.items():
        ytd_credit_map[code] = ytd_credit_map.get(code, Decimal("0")) + v

    return {
        "end_bal":         end_bal,
        "beg_bal":         baseline_end_bal,  # 期初 = 上期期末（不参与 BS 计算，BS 自己反推）
        "cur_debit_map":   cur_debit_map,
        "cur_credit_map":  cur_credit_map,
        "ytd_debit_map":   ytd_debit_map,
        "ytd_credit_map":  ytd_credit_map,
        # IS 明细行回填用：复用基准表的 name 字典（本期凭证按 4 位母科目聚合，没有名称维度）
        "name_ytd_credit": baseline_parsed.get("name_ytd_credit", {}),
        "name_cur_credit": {},
        "name_ytd_debit":  baseline_parsed.get("name_ytd_debit", {}),
        "name_cur_debit":  {},
        "raw_rows":        [],
        "column_mapping":  baseline_parsed.get("column_mapping", {}),
        "row_count":       len(end_bal),
    }


def merge_yearly_and_monthly(yearly: dict, monthly: dict) -> dict:
    """
    把年度文件（1-12月导出）与月度文件（单月导出，如12月）的解析结果合并。
    - 年度文件提供：BS 期末/年初余额、IS 本年累计发生额
    - 月度文件提供：IS 当月发生额（覆盖 cur_*）
    其余字段以年度文件为准。
    """
    merged = dict(yearly)  # 浅拷贝年度结果
    # 用月度文件的"本期发生额"覆盖年度文件的（年度文件里 cur=全年，没用）
    merged["cur_debit_map"]   = monthly["cur_debit_map"]
    merged["cur_credit_map"]  = monthly["cur_credit_map"]
    merged["name_cur_credit"] = monthly.get("name_cur_credit", {})
    merged["name_cur_debit"]  = monthly.get("name_cur_debit",  {})
    return merged


def compute_is_from_trial_balance(parsed: dict, standard: str = "xiye") -> IncomeStatement:
    """用本年累计发生额（优先）或本期发生额计算利润表。"""
    ytd_d = parsed.get("ytd_debit_map", {})
    ytd_c = parsed.get("ytd_credit_map", {})
    cur_d = parsed["cur_debit_map"]
    cur_c = parsed["cur_credit_map"]

    if standard == "xiye":
        # 合并ytd+cur：ytd有的科目用ytd，没有的（IS科目）降级用cur
        d_ytd = _merge_maps(ytd_d, cur_d)
        c_ytd = _merge_maps(ytd_c, cur_c)
        ytd_fn = _make_xiye_fn(d_ytd, c_ytd)
        cur_fn = _make_xiye_fn(cur_d, cur_c)
        is_stmt = _map_income_statement_xiye(ytd_fn, cur_fn, as_of_str="（来自Excel）")

        # 回填IS明细行：根据 row 类型选借方或贷方字典
        # - 费用类明细（利息/招待费/坏账等）走借方字典（_IS_DETAIL_DEBIT_ROWS）
        # - 税金附加等计提类走贷方字典
        name_ytd_credit = parsed.get("name_ytd_credit", {})
        name_cur_credit = parsed.get("name_cur_credit", {})
        name_ytd_debit  = parsed.get("name_ytd_debit",  {})
        name_cur_debit  = parsed.get("name_cur_debit",  {})
        for item in is_stmt.items:
            if item.is_total or item.row_num not in _IS_DETAIL_KEYWORDS:
                continue
            use_debit = item.row_num in _IS_DETAIL_DEBIT_ROWS
            name_ytd  = name_ytd_debit  if use_debit else name_ytd_credit
            name_cur  = name_cur_debit  if use_debit else name_cur_credit
            if not (name_ytd or name_cur):
                continue
            keywords = _IS_DETAIL_KEYWORDS[item.row_num]
            ytd_val = sum(
                v for k, v in name_ytd.items() if any(kw in k for kw in keywords)
            )
            cur_val = sum(
                v for k, v in name_cur.items() if any(kw in k for kw in keywords)
            )
            if ytd_val:
                item.cur_amt = ytd_val
            if cur_val:
                item.prev_amt = cur_val
        return is_stmt

    # 企业准则：本期 vs 上期（无上期数据）
    is_debit  = ytd_d if ytd_d else cur_d
    is_credit = ytd_c if ytd_c else cur_c
    fn      = _make_sum_fn(is_debit, is_credit)
    prev_fn = _make_sum_fn({}, {})
    return _map_income_statement(
        fn, prev_fn,
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
