"""
AgentLedger V4.0 — SubjectService (Sprint 2.1)

职责：
  1. seed_system_subjects()         — 一次性初始化 SystemSubject 标准科目库
  2. init_tenant_subjects()         — 账套骨架软启动：从 SystemSubject 克隆到 TenantSubject
  3. create_subject()               — 新增科目（含编码规范校验）
  4. update_subject()               — 修改科目（铁律：有凭证则锁定 balance_direction/category）
  5. delete_subject()               — 软删除（有发生额则拒绝）
  6. get_subject_tree()             — 返回科目树（递归层级结构）
  7. detect_refactor_opportunity()  — AI 重构探测：扫描传统明细记账，建议升级辅助核算

Iron Law 2 落点：
  update_subject() 检查是否有 voucher_line 记录，有则拒绝修改
  balance_direction 和 category，防止账务逻辑崩溃。

编码规范（subject_code_rule）：
  账套字段 subject_code_rule 默认 "4-2-2-2-2"，表示：
    一级科目 4 位（1001）
    二级科目 = 父编码 + 2 位（100101）
    三级科目 = 父编码 + 2 位（10010101）
  Service 层在新建子科目时校验编码长度是否符合规则。
"""
import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from models.accounting import (
    DEFAULT_NODE_FEATURES,
    BalanceDirection,
    StandardType,
    SubjectCategory,
    SystemSubject,
    TenantSubject,
)
from schemas.subject_schemas import (
    NodeFeatures,
    RefactorSuggestion,
    SubjectCreate,
    SubjectUpdate,
)

logger = logging.getLogger(__name__)


# ── 自定义异常 ──────────────────────────────────────────────────────────────────

class SubjectNotFoundError(Exception):
    pass

class SubjectCodeConflictError(Exception):
    """同一账套内科目编码或名称冲突"""
    pass

class SubjectLockedError(Exception):
    """尝试修改有凭证的科目的锁定字段"""
    pass

class SubjectHasBalanceError(Exception):
    """科目有发生额，禁止删除"""
    pass

class SubjectCodeRuleError(Exception):
    """科目编码不符合账套的编码规范"""
    pass


# ── 系统标准科目种子数据 ────────────────────────────────────────────────────────
# 涵盖《小企业会计准则》和《企业会计准则》共用科目
# standard_type: COMMON=两套均有 / SMALL_BIZ=仅小企业 / GENERAL=仅企业准则
# (code, name, parent, category, direction, level, standard, sort)

_SEED_SUBJECTS: list[tuple] = [
    # ── 资产类 ─────────────────────────────────────────────────────────────
    ("1001", "库存现金",         None,   "资产", "借", 1, "COMMON",    10),
    ("1002", "银行存款",         None,   "资产", "借", 1, "COMMON",    20),
    ("1012", "其他货币资金",     None,   "资产", "借", 1, "COMMON",    30),
    ("1101", "交易性金融资产",   None,   "资产", "借", 1, "GENERAL",   40),
    ("1111", "应收票据",         None,   "资产", "借", 1, "COMMON",    50),
    ("1121", "应收股利",         None,   "资产", "借", 1, "COMMON",    60),
    ("1122", "应收账款",         None,   "资产", "借", 1, "COMMON",    70),
    ("1123", "预付账款",         None,   "资产", "借", 1, "COMMON",    80),
    ("1131", "坏账准备",         None,   "资产", "贷", 1, "COMMON",    85),
    ("1221", "其他应收款",       None,   "资产", "借", 1, "COMMON",    90),
    ("1231", "长期应收款",       None,   "资产", "借", 1, "GENERAL",  100),
    ("1401", "材料采购",         None,   "资产", "借", 1, "COMMON",   110),
    ("1402", "在途物资",         None,   "资产", "借", 1, "COMMON",   120),
    ("1403", "原材料",           None,   "资产", "借", 1, "COMMON",   130),
    ("1405", "库存商品",         None,   "资产", "借", 1, "COMMON",   140),
    ("1406", "发出商品",         None,   "资产", "借", 1, "COMMON",   150),
    ("1501", "长期股权投资",     None,   "资产", "借", 1, "COMMON",   160),
    ("1502", "投资性房地产",     None,   "资产", "借", 1, "GENERAL",  170),
    ("1601", "固定资产",         None,   "资产", "借", 1, "COMMON",   180),
    ("1602", "累计折旧",         None,   "资产", "贷", 1, "COMMON",   190),
    ("1603", "固定资产清理",     None,   "资产", "借", 1, "COMMON",   195),
    ("1604", "在建工程",         None,   "资产", "借", 1, "COMMON",   200),
    ("1606", "固定资产减值准备", None,   "资产", "贷", 1, "GENERAL",  205),
    ("1701", "无形资产",         None,   "资产", "借", 1, "COMMON",   210),
    ("1702", "开发支出",         None,   "资产", "借", 1, "GENERAL",  220),
    ("1703", "累计摊销",         None,   "资产", "贷", 1, "COMMON",   225),
    ("1801", "长期待摊费用",     None,   "资产", "借", 1, "COMMON",   230),
    ("1811", "递延所得税资产",   None,   "资产", "借", 1, "GENERAL",  240),
    ("1901", "待处理财产损溢",   None,   "资产", "借", 1, "COMMON",   250),
    # ── 负债类 ─────────────────────────────────────────────────────────────
    ("2001", "短期借款",         None,   "负债", "贷", 1, "COMMON",   260),
    ("2201", "应付票据",         None,   "负债", "贷", 1, "COMMON",   270),
    ("2202", "应付账款",         None,   "负债", "贷", 1, "COMMON",   280),
    ("2203", "预收款项",         None,   "负债", "贷", 1, "SMALL_BIZ",290),
    ("2205", "合同负债",         None,   "负债", "贷", 1, "GENERAL",  295),
    ("2211", "应付职工薪酬",     None,   "负债", "贷", 1, "COMMON",   300),
    ("2221", "应交税费",         None,   "负债", "贷", 1, "COMMON",   310),
    ("2231", "应付利息",         None,   "负债", "贷", 1, "COMMON",   320),
    ("2232", "应付股利",         None,   "负债", "贷", 1, "COMMON",   330),
    ("2241", "其他应付款",       None,   "负债", "贷", 1, "COMMON",   340),
    ("2401", "递延收益",         None,   "负债", "贷", 1, "COMMON",   350),
    ("2441", "递延所得税负债",   None,   "负债", "贷", 1, "GENERAL",  360),
    ("2501", "长期借款",         None,   "负债", "贷", 1, "COMMON",   370),
    ("2502", "应付债券",         None,   "负债", "贷", 1, "GENERAL",  380),
    ("2511", "长期应付款",       None,   "负债", "贷", 1, "COMMON",   390),
    ("2601", "预计负债",         None,   "负债", "贷", 1, "GENERAL",  400),
    # ── 权益类 ─────────────────────────────────────────────────────────────
    ("4001", "实收资本",         None,   "权益", "贷", 1, "COMMON",   410),
    ("4002", "资本公积",         None,   "权益", "贷", 1, "COMMON",   420),
    ("4005", "其他综合收益",     None,   "权益", "贷", 1, "GENERAL",  425),
    ("4101", "盈余公积",         None,   "权益", "贷", 1, "COMMON",   430),
    ("4103", "本年利润",         None,   "权益", "贷", 1, "COMMON",   440),
    ("4104", "利润分配",         None,   "权益", "贷", 1, "COMMON",   450),
    # ── 成本类 ─────────────────────────────────────────────────────────────
    ("6401", "主营业务成本",     None,   "成本", "借", 1, "COMMON",   460),
    ("6402", "其他业务成本",     None,   "成本", "借", 1, "COMMON",   470),
    # ── 损益类（费用）──────────────────────────────────────────────────────
    ("6403", "税金及附加",       None,   "损益", "借", 1, "COMMON",   480),
    ("6601", "销售费用",         None,   "损益", "借", 1, "COMMON",   490),
    ("6602", "管理费用",         None,   "损益", "借", 1, "COMMON",   500),
    ("6603", "财务费用",         None,   "损益", "借", 1, "COMMON",   510),
    ("6604", "研发费用",         None,   "损益", "借", 1, "GENERAL",  520),
    ("6701", "资产减值损失",     None,   "损益", "借", 1, "GENERAL",  530),
    ("6711", "营业外支出",       None,   "损益", "借", 1, "COMMON",   540),
    ("6801", "所得税费用",       None,   "损益", "借", 1, "COMMON",   550),
    ("6120", "信用减值损失",     None,   "损益", "借", 1, "GENERAL",  555),
    # ── 损益类（收入）──────────────────────────────────────────────────────
    ("6001", "主营业务收入",     None,   "损益", "贷", 1, "COMMON",   560),
    ("6051", "其他业务收入",     None,   "损益", "贷", 1, "COMMON",   570),
    ("6101", "公允价值变动收益", None,   "损益", "贷", 1, "GENERAL",  580),
    ("6111", "投资收益",         None,   "损益", "贷", 1, "COMMON",   590),
    ("6115", "资产处置收益",     None,   "损益", "贷", 1, "GENERAL",  595),
    ("6117", "其他收益",         None,   "损益", "贷", 1, "COMMON",   600),
    ("6301", "营业外收入",       None,   "损益", "贷", 1, "COMMON",   610),
]


# ── 编码规则解析 ────────────────────────────────────────────────────────────────

def _parse_code_rule(rule: str) -> list[int]:
    """
    将编码规则字符串解析为各层级长度列表。
    "4-2-2-2-2" → [4, 6, 8, 10, 12]（累计长度）
    """
    try:
        parts = [int(x) for x in rule.split("-")]
    except ValueError:
        return [4, 6, 8, 10, 12]  # 降级为默认

    cumulative = []
    total = 0
    for p in parts:
        total += p
        cumulative.append(total)
    return cumulative


def _validate_code_against_rule(
    code: str,
    parent_code: str | None,
    rule: str,
) -> None:
    """
    校验 subject_code 是否符合账套的 subject_code_rule 编码规范。
    规则：子科目编码必须以父科目编码为前缀，且总长度符合对应层级要求。
    """
    lengths = _parse_code_rule(rule)

    if parent_code is None:
        # 一级科目：长度必须等于 rule 第一段
        if len(code) != lengths[0]:
            raise SubjectCodeRuleError(
                f"一级科目编码长度必须为 {lengths[0]} 位，当前为 {len(code)} 位（{code}）"
            )
    else:
        # 子科目：必须以父编码为前缀
        if not code.startswith(parent_code):
            raise SubjectCodeRuleError(
                f"子科目编码 '{code}' 必须以父科目编码 '{parent_code}' 为前缀"
            )
        expected_len = None
        parent_len = len(parent_code)
        for cum_len in lengths:
            if cum_len > parent_len:
                expected_len = cum_len
                break
        if expected_len is None:
            raise SubjectCodeRuleError(
                f"科目层级超出编码规则 '{rule}' 的最大层级限制"
            )
        if len(code) != expected_len:
            raise SubjectCodeRuleError(
                f"子科目编码长度应为 {expected_len} 位（父编码 {len(parent_code)} 位 + 延伸），"
                f"当前为 {len(code)} 位（{code}）"
            )


def _infer_level(code: str, parent_code: str | None, rule: str) -> int:
    """根据编码长度推断层级。"""
    lengths = _parse_code_rule(rule)
    code_len = len(code)
    for i, cum_len in enumerate(lengths):
        if code_len == cum_len:
            return i + 1
    return 1


# ── 工具函数 ────────────────────────────────────────────────────────────────────

def _get_subject(db: Session, tenant_id: int, account_set_id: int, subject_code: str) -> TenantSubject:
    obj = (
        db.query(TenantSubject)
        .filter(
            TenantSubject.tenant_id      == tenant_id,
            TenantSubject.account_set_id == account_set_id,
            TenantSubject.subject_code   == subject_code,
            TenantSubject.is_deleted.is_(False),
        )
        .first()
    )
    if not obj:
        raise SubjectNotFoundError(f"科目 '{subject_code}' 不存在")
    return obj


def _has_voucher_lines(db: Session, account_set_id: int, subject_code: str) -> bool:
    """检查该科目在凭证明细中是否已有发生记录。"""
    from models.voucher_line import VoucherLine
    return (
        db.query(VoucherLine.line_id)
        .filter(
            VoucherLine.account_set_id == account_set_id,
            VoucherLine.subject_code   == subject_code,
        )
        .first()
    ) is not None


def _get_account_set_rule(db: Session, account_set_id: int) -> str:
    """获取账套的编码规则，不存在时返回默认值。"""
    from models.account_set import AccountSet
    obj = db.get(AccountSet, account_set_id)
    if obj and hasattr(obj, "subject_code_rule") and obj.subject_code_rule:
        return obj.subject_code_rule
    return "4-2-2-2-2"


# ══════════════════════════════════════════════════════════════════════════════
# SubjectService
# ══════════════════════════════════════════════════════════════════════════════

class SubjectService:

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── 0. 系统科目种子初始化（一次性，idempotent）──────────────────────────

    def seed_system_subjects(self) -> int:
        """
        将 _SEED_SUBJECTS 批量写入 system_subject 表。
        幂等：已存在的科目跳过，仅写入缺失的。
        返回实际写入条数。
        """
        existing_codes = {
            row[0]
            for row in self.db.query(SystemSubject.subject_code).all()
        }
        inserted = 0
        for code, name, parent, cat, direction, level, std, sort in _SEED_SUBJECTS:
            if code in existing_codes:
                continue
            self.db.add(SystemSubject(
                subject_code      = code,
                subject_name      = name,
                parent_code       = parent,
                category          = cat,
                balance_direction = direction,
                level             = level,
                standard_type     = std,
                sort_order        = sort,
            ))
            inserted += 1
        if inserted:
            self.db.commit()
            logger.info("SystemSubject seeded: %d records inserted", inserted)
        return inserted

    # ── 1. 账套骨架软启动 ────────────────────────────────────────────────────

    def init_tenant_subjects(
        self,
        tenant_id:        int,
        account_set_id:   int,
        accounting_standard: str,   # "小企业会计准则" or "企业会计准则"
    ) -> int:
        """
        账套创建后立即调用：从 SystemSubject 全量克隆至 TenantSubject。

        过滤逻辑：
          - COMMON       → 两套准则均克隆
          - SMALL_BIZ    → 仅当 accounting_standard == "小企业会计准则" 时克隆
          - GENERAL      → 仅当 accounting_standard == "企业会计准则" 时克隆

        若 system_subject 表为空（首次部署），先自动执行 seed_system_subjects()。
        返回实际克隆的科目数量。
        """
        # 确保系统科目库已初始化
        if self.db.query(SystemSubject.subject_code).first() is None:
            logger.info("system_subject 为空，自动执行种子初始化")
            self.seed_system_subjects()

        # 确定要克隆的准则类型
        target_std = (
            StandardType.SMALL_BIZ
            if "小企业" in accounting_standard
            else StandardType.GENERAL
        )

        sources = (
            self.db.query(SystemSubject)
            .filter(
                SystemSubject.standard_type.in_(
                    [StandardType.COMMON, target_std]
                )
            )
            .order_by(SystemSubject.sort_order)
            .all()
        )

        # 检查是否已初始化（防重入）
        existing_count = (
            self.db.query(TenantSubject.id)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
            )
            .count()
        )
        if existing_count > 0:
            logger.info(
                "init_tenant_subjects: 账套 %d 已有 %d 条科目，跳过重复初始化",
                account_set_id, existing_count,
            )
            return 0

        default_features_json = json.dumps(DEFAULT_NODE_FEATURES, ensure_ascii=False)
        batch = []
        for src in sources:
            batch.append(TenantSubject(
                tenant_id            = tenant_id,
                account_set_id       = account_set_id,
                subject_code         = src.subject_code,
                subject_name         = src.subject_name,
                parent_code          = src.parent_code,
                category             = src.category,
                balance_direction    = src.balance_direction,
                level                = src.level,
                sort_order           = src.sort_order,
                system_subject_code  = src.subject_code,
                node_features        = default_features_json,
                is_enabled           = True,
                is_deleted           = False,
            ))

        self.db.bulk_save_objects(batch)
        self.db.commit()
        logger.info(
            "init_tenant_subjects: 账套 %d 克隆 %d 条科目（准则：%s）",
            account_set_id, len(batch), accounting_standard,
        )
        return len(batch)

    # ── 2. 新增科目 ─────────────────────────────────────────────────────────

    def create_subject(
        self,
        tenant_id:      int,
        account_set_id: int,
        data:           SubjectCreate,
    ) -> TenantSubject:
        """
        新增自定义科目。
        防呆校验：
          ① 编码规范（subject_code_rule）
          ② 父科目存在性
          ③ 同一账套内编码唯一
          ④ 同一父级下名称不重复
        """
        rule = _get_account_set_rule(self.db, account_set_id)
        _validate_code_against_rule(data.subject_code, data.parent_code, rule)

        # 校验父科目存在
        if data.parent_code:
            parent = (
                self.db.query(TenantSubject)
                .filter(
                    TenantSubject.tenant_id      == tenant_id,
                    TenantSubject.account_set_id == account_set_id,
                    TenantSubject.subject_code   == data.parent_code,
                    TenantSubject.is_deleted.is_(False),
                )
                .first()
            )
            if not parent:
                raise SubjectNotFoundError(
                    f"父科目 '{data.parent_code}' 不存在，请先创建父科目"
                )

        # 编码唯一性
        existing_code = (
            self.db.query(TenantSubject.id)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.subject_code   == data.subject_code,
                TenantSubject.is_deleted.is_(False),
            )
            .first()
        )
        if existing_code:
            raise SubjectCodeConflictError(
                f"科目编码 '{data.subject_code}' 在当前账套中已存在"
            )

        # 同一父级下名称唯一性校验
        existing_name = (
            self.db.query(TenantSubject.id)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.parent_code    == data.parent_code,
                TenantSubject.subject_name   == data.subject_name,
                TenantSubject.is_deleted.is_(False),
            )
            .first()
        )
        if existing_name:
            raise SubjectCodeConflictError(
                f"同一父科目下已存在名称为 '{data.subject_name}' 的科目"
            )

        level = _infer_level(data.subject_code, data.parent_code, rule)
        features_json = json.dumps(
            data.node_features.model_dump(), ensure_ascii=False
        )

        obj = TenantSubject(
            tenant_id         = tenant_id,
            account_set_id    = account_set_id,
            subject_code      = data.subject_code,
            subject_name      = data.subject_name,
            parent_code       = data.parent_code,
            category          = data.category,
            balance_direction = data.balance_direction,
            level             = level,
            sort_order        = data.sort_order,
            node_features     = features_json,
            is_enabled        = True,
            is_deleted        = False,
        )
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        logger.info(
            "TenantSubject created: code=%s name=%s as=%d",
            obj.subject_code, obj.subject_name, account_set_id,
        )
        return obj

    # ── 3. 更新科目（铁律二守门）────────────────────────────────────────────

    def update_subject(
        self,
        tenant_id:      int,
        account_set_id: int,
        subject_code:   str,
        data:           SubjectUpdate,
    ) -> TenantSubject:
        """
        Iron Law 2 守门：
        若该科目已有凭证发生记录，禁止修改 balance_direction 和 category。
        修改这两个字段会导致历史报表逻辑崩溃。
        """
        obj = _get_subject(self.db, tenant_id, account_set_id, subject_code)

        locked_fields_requested = (
            data.balance_direction is not None or data.category is not None
        )
        if locked_fields_requested and _has_voucher_lines(self.db, account_set_id, subject_code):
            raise SubjectLockedError(
                f"科目 '{subject_code}' 已有凭证发生记录，"
                "禁止修改 balance_direction（余额方向）和 category（科目类别）。"
                "若确需修改，请先将相关凭证移至其他科目。"
            )

        if data.subject_name is not None:
            obj.subject_name = data.subject_name.strip()
        if data.balance_direction is not None:
            obj.balance_direction = data.balance_direction
        if data.category is not None:
            obj.category = data.category
        if data.node_features is not None:
            obj.node_features = json.dumps(
                data.node_features.model_dump(), ensure_ascii=False
            )
        if data.is_enabled is not None:
            obj.is_enabled = data.is_enabled
        if data.sort_order is not None:
            obj.sort_order = data.sort_order

        self.db.commit()
        self.db.refresh(obj)
        return obj

    # ── 4. 软删除科目 ────────────────────────────────────────────────────────

    def delete_subject(
        self,
        tenant_id:      int,
        account_set_id: int,
        subject_code:   str,
    ) -> TenantSubject:
        """
        软删除科目。
        禁止条件：
          ① 该科目在 voucher_line 有发生额
          ② 该科目有未删除的子科目（不能删除有子节点的父科目）
        """
        obj = _get_subject(self.db, tenant_id, account_set_id, subject_code)

        if _has_voucher_lines(self.db, account_set_id, subject_code):
            raise SubjectHasBalanceError(
                f"科目 '{subject_code} {obj.subject_name}' 已有凭证发生额，禁止删除。"
                "如需停用请使用【停用】功能（is_enabled=False）。"
            )

        # 检查是否有子科目
        child_count = (
            self.db.query(TenantSubject.id)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.parent_code    == subject_code,
                TenantSubject.is_deleted.is_(False),
            )
            .count()
        )
        if child_count > 0:
            raise SubjectHasBalanceError(
                f"科目 '{subject_code}' 下还有 {child_count} 个子科目，"
                "请先删除所有子科目后再删除父科目。"
            )

        obj.is_deleted = True
        obj.deleted_at = datetime.now()
        self.db.commit()
        self.db.refresh(obj)
        logger.info("TenantSubject soft-deleted: code=%s as=%d", subject_code, account_set_id)
        return obj

    # ── 5. 查询：列表 ────────────────────────────────────────────────────────

    def list_subjects(
        self,
        tenant_id:      int,
        account_set_id: int,
        category:       str | None = None,
        enabled_only:   bool = True,
    ) -> list[TenantSubject]:
        q = self.db.query(TenantSubject).filter(
            TenantSubject.tenant_id      == tenant_id,
            TenantSubject.account_set_id == account_set_id,
            TenantSubject.is_deleted.is_(False),
        )
        if enabled_only:
            q = q.filter(TenantSubject.is_enabled.is_(True))
        if category:
            q = q.filter(TenantSubject.category == category)
        return q.order_by(TenantSubject.sort_order, TenantSubject.subject_code).all()

    def get_subject(
        self,
        tenant_id: int,
        account_set_id: int,
        subject_code: str,
    ) -> TenantSubject:
        return _get_subject(self.db, tenant_id, account_set_id, subject_code)

    # ── 6. 科目树（层级结构）────────────────────────────────────────────────

    def get_subject_tree(
        self,
        tenant_id:      int,
        account_set_id: int,
        enabled_only:   bool = True,
    ) -> list[dict[str, Any]]:
        """
        返回科目树（递归层级结构）。
        底层是一次性 SELECT 全量后在 Python 内存中构建树，避免 N+1 查询。
        """
        all_subjects = self.list_subjects(tenant_id, account_set_id, enabled_only=enabled_only)

        # 构建 code → dict 映射
        node_map: dict[str, dict] = {}
        for s in all_subjects:
            node_map[s.subject_code] = {
                "id":               s.id,
                "subject_code":     s.subject_code,
                "subject_name":     s.subject_name,
                "category":         s.category,
                "balance_direction": s.balance_direction,
                "level":            s.level,
                "is_enabled":       s.is_enabled,
                "node_features":    s.node_features_dict,
                "graph_node_id":    s.graph_node_id,
                "children":         [],
            }

        roots: list[dict] = []
        for s in all_subjects:
            node = node_map[s.subject_code]
            if s.parent_code and s.parent_code in node_map:
                node_map[s.parent_code]["children"].append(node)
            else:
                roots.append(node)

        return roots

    # ── 7. AI 重构探测器（铁律一预埋）──────────────────────────────────────

    def detect_refactor_opportunity(
        self,
        tenant_id:      int,
        account_set_id: int,
        threshold:      int = 10,
    ) -> list[RefactorSuggestion]:
        """
        扫描 TenantSubject，检测传统"明细科目记账"反模式。
        规则：某一科目下挂了超过 threshold 个直接子科目 → 建议升级为辅助核算。

        典型场景（对标柠檬云痛点）：
          1122 应收账款 下挂了 30 个客户名称的三级科目
          → 建议升级为 auxiliary_dimensions: ["customer"]

        返回：RefactorSuggestion 列表，供前端弹窗 AI 向导使用。
        """
        from sqlalchemy import func as sqlfunc

        # 统计每个 parent_code 的子科目数量
        rows = (
            self.db.query(
                TenantSubject.parent_code,
                sqlfunc.count(TenantSubject.id).label("child_count"),
            )
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.is_deleted.is_(False),
                TenantSubject.parent_code.isnot(None),
            )
            .group_by(TenantSubject.parent_code)
            .having(sqlfunc.count(TenantSubject.id) > threshold)
            .all()
        )

        suggestions = []
        for parent_code, child_count in rows:
            try:
                parent = _get_subject(self.db, tenant_id, account_set_id, parent_code)
            except SubjectNotFoundError:
                continue

            # 推断合适的辅助维度
            suggested_dim = _infer_auxiliary_dimension(parent.subject_code, parent.subject_name)

            suggestions.append(RefactorSuggestion(
                subject_code         = parent.subject_code,
                subject_name         = parent.subject_name,
                child_count          = child_count,
                suggestion           = (
                    f"AI 侦测到科目 [{parent.subject_code} {parent.subject_name}] "
                    f"下挂载了 {child_count} 个明细子科目，"
                    f"建议将其升级为【{suggested_dim}辅助核算】，"
                    "维度更清晰，报表汇总更高效。"
                ),
                suggested_dimension  = suggested_dim,
            ))

        logger.info(
            "detect_refactor_opportunity: 账套 %d 发现 %d 个重构建议",
            account_set_id, len(suggestions),
        )
        return suggestions


def _infer_auxiliary_dimension(subject_code: str, subject_name: str) -> str:
    """根据科目编码和名称推断适合的辅助核算维度。"""
    name = subject_name
    if any(k in name for k in ["应收", "客户", "收款"]):
        return "customer"
    if any(k in name for k in ["应付", "供应商", "付款", "采购"]):
        return "supplier"
    if any(k in name for k in ["职工", "薪酬", "工资", "员工", "备用金"]):
        return "employee"
    if any(k in name for k in ["项目", "工程", "合同"]):
        return "project"
    if any(k in name for k in ["部门", "费用"]):
        return "dept"
    return "customer"   # 默认兜底


    # ── 内部：账套克隆时深度复制科目树 ──────────────────────────────────────

    def _clone_subjects_from(
        self,
        src_tenant_id:      int,
        src_account_set_id: int,
        dst_account_set_id: int,
    ) -> int:
        """
        从源账套深度复制 TenantSubject 到目标账套。
        仅复制科目结构和 node_features 配置，不复制余额和凭证。
        目标账套已有科目时跳过（防重入）。
        """
        existing = (
            self.db.query(TenantSubject.id)
            .filter(
                TenantSubject.tenant_id      == src_tenant_id,
                TenantSubject.account_set_id == dst_account_set_id,
            )
            .count()
        )
        if existing > 0:
            return 0

        sources = (
            self.db.query(TenantSubject)
            .filter(
                TenantSubject.tenant_id      == src_tenant_id,
                TenantSubject.account_set_id == src_account_set_id,
                TenantSubject.is_deleted.is_(False),
            )
            .order_by(TenantSubject.sort_order, TenantSubject.subject_code)
            .all()
        )

        batch = [
            TenantSubject(
                tenant_id           = src_tenant_id,
                account_set_id      = dst_account_set_id,
                subject_code        = s.subject_code,
                subject_name        = s.subject_name,
                parent_code         = s.parent_code,
                category            = s.category,
                balance_direction   = s.balance_direction,
                level               = s.level,
                sort_order          = s.sort_order,
                system_subject_code = s.system_subject_code,
                node_features       = s.node_features,
                is_enabled          = s.is_enabled,
                is_deleted          = False,
            )
            for s in sources
        ]
        self.db.bulk_save_objects(batch)
        self.db.flush()
        return len(batch)
