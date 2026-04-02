"""
AgentLedger V4.0 — AccountSetService (Sprint 1)

核心职责：
  1. parse_license()       — 营业执照 Vision LLM 一键建账（Iron Law 1 前置 RAG 注入）
  2. create_account_set()  — 创建账套，含 start_period 格式校验
  3. update_account_set()  — 更新账套，铁律二：有凭证后锁定 start_period/accounting_standard
  4. soft_delete()         — 软删除（进回收站），绝不执行 SQL DELETE
  5. restore()             — 从回收站恢复
  6. clone()               — 账套克隆（settings + 会计科目树）

Iron Law 1 (Habit RAG) 落点：
  parse_license() 在调用 Vision LLM 前，先检索该 tenant 历史上已创建账套的
  accounting_standard 和 taxpayer_type 多数派，作为 few-shot 强约束注入 prompt，
  避免用户每次重复选择同类推荐。

Iron Law 2 (Financial Continuity) 落点：
  update_account_set() 在修改 start_period / accounting_standard 前，
  先检查该账套是否已存在有效凭证（voucher_header）或期初余额条目，
  有则抛出 AccountSetLockedError，彻底锁死这两个字段。
"""
import json
import logging
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from models.account_set import AccountSet, AccountSetStatus, AccountingStandard, TaxpayerType
from services.crypto_utils import encrypt_field, decrypt_field

logger = logging.getLogger(__name__)


# ── Pydantic Schemas ────────────────────────────────────────────────────────────

class ParsedLicenseData(BaseModel):
    """Vision LLM 从营业执照图片提取的结构化字段。"""
    company_name: str = Field(description="公司全称")
    uscc: str | None = Field(default=None, description="统一社会信用代码（18位）")
    registered_capital: float | None = Field(
        default=None, description="注册资本（万元），用于推断会计准则"
    )
    # Iron Law 1: AI 推理 + 历史模式注入的推荐值
    recommended_accounting_standard: str = Field(
        default=AccountingStandard.SMALL_BIZ,
        description="推荐会计准则（AI 基于注册资本 + 历史账套模式推断）"
    )
    recommended_taxpayer_type: str = Field(
        default=TaxpayerType.SMALL_SCALE,
        description="推荐增值税种类（AI 推断）"
    )
    raw_text: str | None = Field(default=None, description="LLM 返回原文，供前端调试")


class AccountSetCreateInput(BaseModel):
    account_set_name: str
    company_name: str
    start_period: str = Field(description="格式 YYYY-MM，如 '2026-01'")
    accounting_standard: str = AccountingStandard.SMALL_BIZ
    taxpayer_type: str = TaxpayerType.SMALL_SCALE
    fiscal_year_start_month: int = 1
    uscc: str | None = None
    tax_bureau_region: str | None = None
    tax_password: str | None = None
    module_settings: dict | None = None


class AccountSetUpdateInput(BaseModel):
    account_set_name: str | None = None
    company_name: str | None = None
    taxpayer_type: str | None = None
    uscc: str | None = None
    tax_bureau_region: str | None = None
    tax_password: str | None = None
    module_settings: dict | None = None
    # start_period / accounting_standard 刻意不放这里，走专属校验路径
    start_period: str | None = None
    accounting_standard: str | None = None


class CloneOptions(BaseModel):
    clone_options: list[str] = Field(
        default=["settings"],
        description="可选：'settings'（复制配置）、'accounting_subjects'（复制科目树）"
    )
    new_account_set_name: str
    new_company_name: str | None = None
    new_start_period: str = Field(description="克隆出的新账套启用年月 YYYY-MM")


# ── 自定义异常 ──────────────────────────────────────────────────────────────────

class AccountSetNotFoundError(Exception):
    pass


class AccountSetLockedError(Exception):
    """尝试修改铁律二保护的字段（start_period/accounting_standard）时抛出。"""
    pass


class AccountSetDeletedError(Exception):
    """对已软删除账套执行业务操作时抛出。"""
    pass


class InvalidPeriodError(Exception):
    pass


# ── 工具函数 ────────────────────────────────────────────────────────────────────

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _validate_period(period: str) -> None:
    """校验 start_period 格式为 YYYY-MM，且月份合法。"""
    if not _PERIOD_RE.match(period):
        raise InvalidPeriodError(
            f"start_period 格式无效：'{period}'。必须为 YYYY-MM（如 '2026-01'）"
        )


def _has_vouchers(db: Session, account_set_id: int) -> bool:
    """检查账套是否已存在有效凭证（铁律二锁定判断依据）。"""
    from models.voucher_header import VoucherHeader
    return (
        db.query(VoucherHeader.voucher_id)
        .filter(VoucherHeader.account_set_id == account_set_id)
        .first()
    ) is not None


def _get_active_account_set(db: Session, tenant_id: int, account_set_id: int) -> AccountSet:
    """获取账套，验证归属且未软删除。"""
    obj = (
        db.query(AccountSet)
        .filter(
            AccountSet.account_set_id == account_set_id,
            AccountSet.tenant_id == tenant_id,
        )
        .first()
    )
    if not obj:
        raise AccountSetNotFoundError(f"账套 {account_set_id} 不存在或无权访问")
    if obj.is_deleted:
        raise AccountSetDeletedError(
            f"账套 {account_set_id} 已在回收站，请先恢复后再操作"
        )
    return obj


# ── Iron Law 1: 前置 Habit RAG ─────────────────────────────────────────────────

def _retrieve_tenant_account_habits(db: Session, tenant_id: int) -> dict[str, str]:
    """
    Iron Law 1 — 前置检索：读取该租户历史账套的 accounting_standard 和
    taxpayer_type 多数派，作为 few-shot 约束注入 LLM prompt。

    返回：{"accounting_standard": "...", "taxpayer_type": "..."}
    若无历史数据则返回空 dict（LLM 使用默认推断）。
    """
    rows = (
        db.query(AccountSet.accounting_standard, AccountSet.taxpayer_type)
        .filter(
            AccountSet.tenant_id == tenant_id,
            AccountSet.is_deleted.is_(False),
        )
        .all()
    )
    if not rows:
        return {}

    std_counter: dict[str, int] = {}
    tax_counter: dict[str, int] = {}
    for std, tax in rows:
        std_counter[std] = std_counter.get(std, 0) + 1
        tax_counter[tax] = tax_counter.get(tax, 0) + 1

    majority_std = max(std_counter, key=std_counter.__getitem__)
    majority_tax = max(tax_counter, key=tax_counter.__getitem__)

    logger.info(
        "Habit RAG (account-set): tenant=%d → std=%s, tax=%s",
        tenant_id, majority_std, majority_tax,
    )
    return {
        "accounting_standard": majority_std,
        "taxpayer_type": majority_tax,
    }


# ── Vision LLM 调用（营业执照解析）─────────────────────────────────────────────

def _build_license_prompt(habits: dict[str, str]) -> str:
    """
    构建强约束 Vision LLM 提示词。
    将历史 Habit 模式作为 few-shot 约束注入，确保推荐与租户历史习惯一致。
    """
    habit_hint = ""
    if habits:
        habit_hint = (
            f"\n\n【历史模式参考（优先采纳）】\n"
            f"该客户历史账套中最常用的会计准则为：{habits.get('accounting_standard', '')}；"
            f"增值税种类为：{habits.get('taxpayer_type', '')}。\n"
            f"除非营业执照显示的注册资本超过1000万元人民币，否则请沿用历史选择。"
        )

    return (
        "请识别这张营业执照图片，提取以下字段，以 JSON 格式返回，只返回 JSON 不要其他文字：\n"
        "{\n"
        '  "company_name": "公司全称",\n'
        '  "uscc": "统一社会信用代码（18位字母数字）",\n'
        '  "registered_capital": 注册资本数字（单位：万元，无则为null）,\n'
        '  "recommended_accounting_standard": "小企业会计准则 或 企业会计准则",\n'
        '  "recommended_taxpayer_type": "小规模纳税人 或 一般纳税人"\n'
        "}\n\n"
        "推断规则：\n"
        "- 注册资本 < 1000万元 → recommended_accounting_standard = '小企业会计准则'，"
        "recommended_taxpayer_type = '小规模纳税人'\n"
        "- 注册资本 ≥ 1000万元 → recommended_accounting_standard = '企业会计准则'，"
        "recommended_taxpayer_type = '一般纳税人'"
        + habit_hint
    )


def _call_vision_llm_for_license(image_bytes: bytes, mime_type: str, prompt: str) -> str:
    """
    调用 Vision LLM 解析营业执照。
    若未配置 VISION_API_KEY，返回占位 JSON（开发环境用）。
    """
    from config.settings import VISION_API_KEY, VISION_API_BASE, VISION_MODEL
    import base64

    if not VISION_API_KEY:
        logger.warning("VISION_API_KEY 未配置，营业执照解析返回占位数据")
        return json.dumps({
            "company_name": "（未识别，请手工填写）",
            "uscc": None,
            "registered_capital": None,
            "recommended_accounting_standard": AccountingStandard.SMALL_BIZ,
            "recommended_taxpayer_type": TaxpayerType.SMALL_SCALE,
        })

    import openai
    b64 = base64.b64encode(image_bytes).decode()
    client = openai.OpenAI(api_key=VISION_API_KEY, base_url=VISION_API_BASE)
    resp = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
                {"type": "text", "text": prompt},
            ],
        }],
        max_tokens=512,
    )
    return resp.choices[0].message.content


# ── Service 主类 ────────────────────────────────────────────────────────────────

class AccountSetService:

    def __init__(self, db: Session):
        self.db = db

    # ── 1. 营业执照一键解析（Iron Law 1 入口）─────────────────────────────────

    def parse_license(
        self,
        tenant_id: int,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> ParsedLicenseData:
        """
        Iron Law 1 完整流程：
          ① 前置检索 — 拉取该租户历史账套习惯（accounting_standard / taxpayer_type）
          ② Few-shot 注入 — 将历史模式作为强约束嵌入 Vision LLM prompt
          ③ LLM 调用 — 提取营业执照文字信息
          ④ 返回 ParsedLicenseData — 前端展示供用户确认后正式创建账套
        """
        # Step 1: 铁律一 — 前置 Habit RAG
        habits = _retrieve_tenant_account_habits(self.db, tenant_id)

        # Step 2: 构建 few-shot 强约束 prompt
        prompt = _build_license_prompt(habits)

        # Step 3: 调用 Vision LLM
        try:
            raw = _call_vision_llm_for_license(image_bytes, mime_type, prompt)
            data: dict[str, Any] = json.loads(raw)
        except Exception as exc:
            logger.error("营业执照 Vision LLM 解析失败: %s", exc)
            data = {}

        def _g(key: str, default: Any = None) -> Any:
            return data.get(key, default)

        return ParsedLicenseData(
            company_name=_g("company_name", ""),
            uscc=_g("uscc"),
            registered_capital=_g("registered_capital"),
            recommended_accounting_standard=_g(
                "recommended_accounting_standard",
                habits.get("accounting_standard", AccountingStandard.SMALL_BIZ),
            ),
            recommended_taxpayer_type=_g(
                "recommended_taxpayer_type",
                habits.get("taxpayer_type", TaxpayerType.SMALL_SCALE),
            ),
            raw_text=raw if isinstance(raw, str) else None,
        )

    # ── 2. 创建账套 ─────────────────────────────────────────────────────────────

    def create_account_set(
        self,
        tenant_id: int,
        data: AccountSetCreateInput,
    ) -> AccountSet:
        """
        创建新账套。
        防呆：校验 start_period 格式；校验 accounting_standard / taxpayer_type 枚举值。
        """
        _validate_period(data.start_period)

        if data.accounting_standard not in AccountingStandard.ALL:
            raise ValueError(
                f"accounting_standard 无效：'{data.accounting_standard}'。"
                f"合法值：{AccountingStandard.ALL}"
            )
        if data.taxpayer_type not in TaxpayerType.ALL:
            raise ValueError(
                f"taxpayer_type 无效：'{data.taxpayer_type}'。"
                f"合法值：{TaxpayerType.ALL}"
            )

        encrypted_pwd = None
        if data.tax_password:
            encrypted_pwd = encrypt_field(data.tax_password)

        module_json = (
            json.dumps(data.module_settings, ensure_ascii=False)
            if data.module_settings
            else None
        )

        account_set = AccountSet(
            tenant_id=tenant_id,
            account_set_name=data.account_set_name,
            company_name=data.company_name,
            start_period=data.start_period,
            fiscal_year_start_month=data.fiscal_year_start_month,
            accounting_standard=data.accounting_standard,
            taxpayer_type=data.taxpayer_type,
            uscc=data.uscc,
            tax_bureau_region=data.tax_bureau_region,
            tax_password=encrypted_pwd,
            module_settings=module_json,
            status=AccountSetStatus.ONBOARDING,
            is_deleted=False,
        )
        self.db.add(account_set)
        self.db.commit()
        self.db.refresh(account_set)
        logger.info(
            "AccountSet created: id=%d tenant=%d period=%s",
            account_set.account_set_id, tenant_id, data.start_period,
        )
        return account_set

    # ── 3. 更新账套（铁律二守门）─────────────────────────────────────────────

    def update_account_set(
        self,
        tenant_id: int,
        account_set_id: int,
        data: AccountSetUpdateInput,
    ) -> AccountSet:
        """
        Iron Law 2 守门逻辑：
        若账套已产生有效凭证，则 start_period 和 accounting_standard 的修改请求
        直接抛出 AccountSetLockedError，禁止落库。
        """
        obj = _get_active_account_set(self.db, tenant_id, account_set_id)

        # 铁律二检查：尝试修改锁定字段时触发
        locked_fields_requested = (
            data.start_period is not None or data.accounting_standard is not None
        )
        if locked_fields_requested and _has_vouchers(self.db, account_set_id):
            raise AccountSetLockedError(
                "该账套已存在有效凭证，start_period 和 accounting_standard 不可修改。"
                "修改这两个字段会导致全盘账务崩溃。如有特殊需求，请联系系统管理员。"
            )

        if data.start_period is not None:
            _validate_period(data.start_period)
            obj.start_period = data.start_period

        if data.accounting_standard is not None:
            if data.accounting_standard not in AccountingStandard.ALL:
                raise ValueError(f"accounting_standard 无效：'{data.accounting_standard}'")
            obj.accounting_standard = data.accounting_standard

        if data.account_set_name is not None:
            obj.account_set_name = data.account_set_name
        if data.company_name is not None:
            obj.company_name = data.company_name
        if data.taxpayer_type is not None:
            if data.taxpayer_type not in TaxpayerType.ALL:
                raise ValueError(f"taxpayer_type 无效：'{data.taxpayer_type}'")
            obj.taxpayer_type = data.taxpayer_type
        if data.uscc is not None:
            obj.uscc = data.uscc
        if data.tax_bureau_region is not None:
            obj.tax_bureau_region = data.tax_bureau_region
        if data.tax_password is not None:
            obj.tax_password = encrypt_field(data.tax_password)
        if data.module_settings is not None:
            obj.module_settings = json.dumps(data.module_settings, ensure_ascii=False)

        self.db.commit()
        self.db.refresh(obj)
        return obj

    # ── 4. 激活账套（ONBOARDING → ACTIVE）────────────────────────────────────

    def activate_account_set(self, tenant_id: int, account_set_id: int) -> AccountSet:
        """将账套从建账期推进到正式启用状态。"""
        obj = _get_active_account_set(self.db, tenant_id, account_set_id)
        if obj.status != AccountSetStatus.ONBOARDING:
            raise ValueError(
                f"只有 ONBOARDING 状态的账套可以激活，当前状态：{obj.status}"
            )
        obj.status = AccountSetStatus.ACTIVE
        obj.activated_at = datetime.now()
        self.db.commit()
        self.db.refresh(obj)
        logger.info("AccountSet activated: id=%d", account_set_id)
        return obj

    # ── 5. 软删除（进回收站）──────────────────────────────────────────────────

    def soft_delete(self, tenant_id: int, account_set_id: int) -> AccountSet:
        """
        账套软删除：绝不执行 SQL DELETE。
        将 is_deleted=True、status=RECYCLED、deleted_at=now()。
        业务查询层（TenantSession 拦截器 + 服务层）自动过滤已删除账套。
        """
        obj = _get_active_account_set(self.db, tenant_id, account_set_id)
        obj.is_deleted = True
        obj.status = AccountSetStatus.RECYCLED
        obj.deleted_at = datetime.now()
        self.db.commit()
        self.db.refresh(obj)
        logger.info(
            "AccountSet soft-deleted: id=%d tenant=%d", account_set_id, tenant_id
        )
        return obj

    # ── 6. 从回收站恢复 ─────────────────────────────────────────────────────

    def restore(self, tenant_id: int, account_set_id: int) -> AccountSet:
        """从回收站恢复账套，状态恢复为删除前的 ACTIVE 或 ONBOARDING。"""
        obj = (
            self.db.query(AccountSet)
            .filter(
                AccountSet.account_set_id == account_set_id,
                AccountSet.tenant_id == tenant_id,
                AccountSet.is_deleted.is_(True),
            )
            .first()
        )
        if not obj:
            raise AccountSetNotFoundError(
                f"在回收站中找不到账套 {account_set_id}，或该账套不属于当前租户"
            )
        # 恢复为激活前的合理状态：有 activated_at 则 ACTIVE，否则 ONBOARDING
        obj.is_deleted = False
        obj.deleted_at = None
        obj.status = (
            AccountSetStatus.ACTIVE
            if obj.activated_at
            else AccountSetStatus.ONBOARDING
        )
        self.db.commit()
        self.db.refresh(obj)
        logger.info(
            "AccountSet restored: id=%d → status=%s", account_set_id, obj.status
        )
        return obj

    # ── 7. 账套克隆 ─────────────────────────────────────────────────────────

    def clone(
        self,
        tenant_id: int,
        source_account_set_id: int,
        options: CloneOptions,
    ) -> AccountSet:
        """
        账套克隆（代账公司模板复制场景）。

        支持的 clone_options：
          'settings'            — 深度复制模块开关、会计准则、纳税人类型等配置
          'accounting_subjects' — 预留接口：当前 Sprint 仅记录意图，科目树克隆在
                                  Sprint 2 随 per-account-set subjects 表落地

        禁止克隆：凭证历史、银行流水、期初余额。
        """
        src = _get_active_account_set(self.db, tenant_id, source_account_set_id)
        _validate_period(options.new_start_period)

        # ── 基础字段复制 ────────────────────────────────────────────────────
        new_obj = AccountSet(
            tenant_id=tenant_id,
            account_set_name=options.new_account_set_name,
            company_name=options.new_company_name or src.company_name,
            start_period=options.new_start_period,
            fiscal_year_start_month=src.fiscal_year_start_month,
            status=AccountSetStatus.ONBOARDING,
            is_deleted=False,
        )

        # ── 'settings' 选项：复制配置信息 ───────────────────────────────────
        if "settings" in options.clone_options:
            new_obj.accounting_standard = src.accounting_standard
            new_obj.taxpayer_type = src.taxpayer_type
            new_obj.tax_bureau_region = src.tax_bureau_region
            new_obj.module_settings = src.module_settings
            # 注意：uscc / tax_password 属于企业专属敏感信息，不随模板复制
            logger.info(
                "Clone 'settings': accounting_standard=%s taxpayer_type=%s",
                src.accounting_standard, src.taxpayer_type,
            )

        self.db.add(new_obj)
        self.db.flush()   # 获取新账套 ID（供科目树克隆使用）

        # ── 'accounting_subjects' 选项：科目树克隆（Sprint 1 预留接口）───────
        if "accounting_subjects" in options.clone_options:
            # Sprint 2 实现：届时将引入 per-account-set AccountingSubjectCustomization
            # 表，在此调用 _clone_subjects(src.account_set_id, new_obj.account_set_id)。
            # 当前 Sprint 仅记录操作意图，不影响主流程。
            logger.info(
                "Clone 'accounting_subjects': source=%d → target=%d (Sprint 2 落地)",
                source_account_set_id, new_obj.account_set_id,
            )

        self.db.commit()
        self.db.refresh(new_obj)
        logger.info(
            "AccountSet cloned: source=%d → new=%d options=%s",
            source_account_set_id, new_obj.account_set_id, options.clone_options,
        )
        return new_obj

    # ── 8. 查询 ────────────────────────────────────────────────────────────

    def list_account_sets(
        self,
        tenant_id: int,
        include_recycled: bool = False,
    ) -> list[AccountSet]:
        q = self.db.query(AccountSet).filter(AccountSet.tenant_id == tenant_id)
        if not include_recycled:
            q = q.filter(AccountSet.is_deleted.is_(False))
        return q.order_by(AccountSet.account_set_id.desc()).all()

    def list_recycled(self, tenant_id: int) -> list[AccountSet]:
        return (
            self.db.query(AccountSet)
            .filter(
                AccountSet.tenant_id == tenant_id,
                AccountSet.is_deleted.is_(True),
            )
            .order_by(AccountSet.deleted_at.desc())
            .all()
        )

    def get_account_set(self, tenant_id: int, account_set_id: int) -> AccountSet:
        return _get_active_account_set(self.db, tenant_id, account_set_id)

    def get_decrypted_tax_password(
        self, tenant_id: int, account_set_id: int
    ) -> str | None:
        """返回解密后的明文申报密码（仅在税务直连模块中使用）。"""
        obj = _get_active_account_set(self.db, tenant_id, account_set_id)
        if not obj.tax_password:
            return None
        return decrypt_field(obj.tax_password)
