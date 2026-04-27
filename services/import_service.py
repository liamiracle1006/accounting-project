"""
AgentLedger V4.0 — ImportService (Sprint 2.3)

旧账导入全流程服务，四个阶段：

  阶段一：create_session + get_export_guide
           — 创建导入会话，返回旧系统导出操作提示

  阶段二：upload_and_clean
           — Pandas 物理清洗 + LLM 表头映射 + 写入 ImportStaging

  阶段三：map_subjects + get_abnormal_subjects + confirm_subject + skip_subject
           — AI 科目匹配引擎（精确匹配 / 智能派生 / 人工复核）

  阶段四：execute_import
           — CONFIRMED 行结转 InitialBalance + complete_account_setup 海绵兜底

常量：
  IMPORT_PREVIEW_ROWS = 20   ← 发送给 LLM 进行表头分析的预览行数，可按需调整
  SUBJECT_MATCH_BATCH = 50   ← 每次发送给 LLM 进行科目匹配的最大行数
  HIGH_CONFIDENCE     = 0.95 ← 高置信度阈值：直接 CONFIRMED
  DERIVE_CONFIDENCE   = 0.85 ← 中置信度阈值：尝试智能派生
"""
import io
import json
import logging
import math
from datetime import datetime

from sqlalchemy.orm import Session

from ai.llm_client import LLMClient, LLMClientError
from models.accounting import TenantSubject
from models.account_set import AccountSet
from models.import_session import (
    ImportSession,
    ImportSessionStatus,
    ImportStaging,
    ImportStagingStatus,
)
from schemas.import_schemas import CreateSessionInput
from schemas.initial_balance_schemas import InitialBalanceInput
from schemas.subject_schemas import SubjectCreate, NodeFeatures
from services.initial_balance_service import InitialBalanceService
from services.subject_service import SubjectService, SubjectCodeConflictError, SubjectCodeRuleError

logger = logging.getLogger(__name__)

# ── 可修改常量 ──────────────────────────────────────────────────────────────────
IMPORT_PREVIEW_ROWS = 20   # 发送给 LLM 进行表头分析的预览行数
SUBJECT_MATCH_BATCH = 50   # 每批次发送给 LLM 进行科目匹配的最大科目数
HIGH_CONFIDENCE     = 0.95 # 高置信度：直接 CONFIRMED（不派生，直接用 matched_code）
DERIVE_CONFIDENCE   = 0.85 # 中置信度：尝试智能派生子科目，失败则降级 PENDING_REVIEW


# ── 自定义异常 ──────────────────────────────────────────────────────────────────

class ImportSessionNotFoundError(Exception):
    pass

class ImportSessionStatusError(Exception):
    """当前会话状态不允许执行该操作"""
    pass

class ImportStagingNotFoundError(Exception):
    pass


# ── 内部辅助函数 ────────────────────────────────────────────────────────────────

def _parse_amount(raw) -> float | None:
    """将任意原始值（字符串/数字/NaN）安全转换为 float，失败返回 None。"""
    if raw is None:
        return None
    if isinstance(raw, float) and math.isnan(raw):
        return None
    try:
        return float(str(raw).replace(",", "").replace("，", "").strip())
    except (ValueError, TypeError):
        return None


def _normalize_direction(raw) -> str | None:
    """将各系统的余额方向表示统一为 '借' / '贷'，无法识别返回 None。"""
    if raw is None:
        return None
    v = str(raw).strip()
    if v in ("借", "Dr", "D", "debit", "DEBIT", "借方", "1"):
        return "借"
    if v in ("贷", "Cr", "C", "credit", "CREDIT", "贷方", "2"):
        return "贷"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# ImportService
# ══════════════════════════════════════════════════════════════════════════════

class ImportService:

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── 内部：获取会话（带租户隔离校验） ───────────────────────────────────────

    def _get_session(
        self,
        session_id:     int,
        tenant_id:      int,
        account_set_id: int,
    ) -> ImportSession:
        obj = (
            self.db.query(ImportSession)
            .filter(
                ImportSession.session_id     == session_id,
                ImportSession.tenant_id      == tenant_id,
                ImportSession.account_set_id == account_set_id,
            )
            .first()
        )
        if obj is None:
            raise ImportSessionNotFoundError(f"导入会话 {session_id} 不存在")
        return obj

    # ══════════════════════════════════════════════════════════════════════════
    # 阶段一：会话创建 + 导出向导
    # ══════════════════════════════════════════════════════════════════════════

    def create_session(
        self,
        tenant_id:      int,
        account_set_id: int,
        data:           CreateSessionInput,
    ) -> ImportSession:
        """创建新的导入会话，状态初始为 UPLOADING。"""
        obj = ImportSession(
            tenant_id         = tenant_id,
            account_set_id    = account_set_id,
            source_system     = data.source_system,
            status            = ImportSessionStatus.UPLOADING.value,
            original_filename = data.original_filename,
        )
        self.db.add(obj)
        self.db.flush()
        return obj

    def get_export_guide(self, source_system: str) -> dict:
        """
        返回针对指定旧系统的导出操作提示（纯静态数据，不访问 DB）。
        前端向导页直接渲染。
        """
        guides: dict[str, dict] = {
            "金蝶": {
                "tips": [
                    "进入【财务会计】→【账表】→【科目余额表】",
                    "导出时务必勾选【包含未过账凭证】",
                    "勾选【显示核算明细】以展开辅助核算科目",
                    "选择导出范围：从会计期间起始月至当前期间",
                    "导出格式选择【Excel (.xlsx)】",
                ],
                "sample_columns": ["科目编码", "科目名称", "方向", "期末余额",
                                   "本年借方合计", "本年贷方合计"],
            },
            "用友": {
                "tips": [
                    "进入【财务会计】→【总账】→【科目余额】",
                    "选择【科目余额表】，设置期间为年初至当前月",
                    "勾选【显示明细科目】",
                    "导出格式选择【Excel】",
                ],
                "sample_columns": ["编码", "名称", "借贷", "余额",
                                   "本年借方", "本年贷方"],
            },
            "管家婆": {
                "tips": [
                    "进入【财务】→【账表查询】→【科目汇总表】",
                    "选择期间：从账套起始月至当前月",
                    "勾选【显示期初余额】",
                    "点击【导出Excel】",
                ],
                "sample_columns": ["账户代码", "账户名称", "借方期初",
                                   "贷方期初", "借方发生", "贷方发生"],
            },
            "其他Excel": {
                "tips": [
                    "确保Excel文件包含：科目编码、科目名称、余额方向（借/贷）",
                    "建议包含：期初余额、本年累计借方、本年累计贷方",
                    "删除合并单元格，确保每行数据完整",
                    "文件格式须为 .xlsx 或 .xls",
                ],
                "sample_columns": ["科目编码", "科目名称", "余额方向",
                                   "期初余额", "本年借方", "本年贷方"],
            },
        }
        info = guides.get(source_system, guides["其他Excel"])
        return {
            "source_system":  source_system,
            "tips":           info["tips"],
            "sample_columns": info["sample_columns"],
        }

    # ══════════════════════════════════════════════════════════════════════════
    # 阶段二：文件上传 + Pandas 物理清洗 + LLM 表头映射
    # ══════════════════════════════════════════════════════════════════════════

    def upload_and_clean(
        self,
        session_id:     int,
        tenant_id:      int,
        account_set_id: int,
        file_bytes:     bytes,
    ) -> dict:
        """
        1. Pandas 读取 Excel：dropna(how='all') + ffill 解决合并单元格
        2. 提取前 IMPORT_PREVIEW_ROWS 行喂给 LLM，获取列名映射
        3. 应用映射，将每行数据写入 ImportStaging
        4. 会话状态 → MAPPING
        返回 {session_id, rows_loaded, columns_found, header_mapping, warnings}
        """
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas 未安装，请执行 pip install 'pandas>=2.2.0'")

        session = self._get_session(session_id, tenant_id, account_set_id)
        if session.status not in (
            ImportSessionStatus.UPLOADING.value,
            ImportSessionStatus.MAPPING.value,   # 允许重新上传
        ):
            raise ImportSessionStatusError(
                f"会话 {session_id} 状态为 {session.status}，不允许重新上传文件"
            )

        warnings: list[str] = []

        # ── Step 1: Pandas 物理清洗 ─────────────────────────────────────────
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
        except Exception as exc:
            raise ValueError(f"Excel 文件解析失败：{exc}") from exc

        # 清理全空行列
        df = df.dropna(how="all")
        df = df.dropna(axis=1, how="all")

        # ffill 解决传统报表合并单元格（同一科目大类跨多行）
        df = df.ffill()

        # 去掉列名两端空白
        df.columns = [str(c).strip() for c in df.columns]
        columns_found = list(df.columns)

        if df.empty:
            raise ValueError("Excel 文件清洗后为空，请检查文件内容")

        # ── Step 2: 提取预览行，调用 LLM 推断列名映射 ──────────────────────
        preview_rows = (
            df.head(IMPORT_PREVIEW_ROWS)
            .fillna("")
            .to_dict(orient="records")
        )
        preview_payload = json.dumps(
            {
                "source_system": session.source_system,
                "columns":       columns_found,
                "preview":       preview_rows,
            },
            ensure_ascii=False,
        )

        try:
            llm    = LLMClient()
            raw    = llm.map_excel_headers(preview_payload)
            mapping: dict = json.loads(raw)
        except (LLMClientError, json.JSONDecodeError) as exc:
            logger.warning("LLM 表头映射失败，降级为人工确认模式：%s", exc)
            mapping = {k: None for k in (
                "subject_code", "subject_name", "balance_direction",
                "initial_balance", "ytd_debit", "ytd_credit",
            )}
            warnings.append(f"AI 表头识别失败（{exc}），请手动确认列名映射后重试")

        # 校验 mapping 结构，补全缺失键
        standard_fields = (
            "subject_code", "subject_name", "balance_direction",
            "initial_balance", "ytd_debit", "ytd_credit",
        )
        for field in standard_fields:
            if field not in mapping:
                mapping[field] = None

        # 保存映射到会话
        session.header_mapping = mapping

        # ── Step 3: 删除该会话已有 staging 行（重新上传场景） ───────────────
        self.db.query(ImportStaging).filter(
            ImportStaging.session_id     == session_id,
            ImportStaging.tenant_id      == tenant_id,
            ImportStaging.account_set_id == account_set_id,
        ).delete(synchronize_session=False)

        # ── Step 4: 将全量数据写入 ImportStaging ───────────────────────────
        def _col(row: dict, field_name: str):
            """从 row 中取映射列的值，映射为 None 或列不存在时返回 None。"""
            col = mapping.get(field_name)
            if not col:
                return None
            return row.get(col)

        rows_loaded = 0
        for idx, row in enumerate(df.fillna("").to_dict(orient="records"), start=2):
            # 跳过全空行（ffill 后仍然全空的行）
            raw_code = str(_col(row, "subject_code") or "").strip()
            raw_name = str(_col(row, "subject_name") or "").strip()
            if not raw_code and not raw_name:
                continue

            raw_direction = str(_col(row, "balance_direction") or "").strip() or None
            raw_initial   = str(_col(row, "initial_balance") or "").strip() or None
            raw_debit     = str(_col(row, "ytd_debit") or "").strip() or None
            raw_credit    = str(_col(row, "ytd_credit") or "").strip() or None

            staging = ImportStaging(
                session_id     = session_id,
                tenant_id      = tenant_id,
                account_set_id = account_set_id,
                row_number     = idx,

                raw_subject_code      = raw_code or None,
                raw_subject_name      = raw_name or None,
                raw_balance_direction = raw_direction,
                raw_initial_balance   = raw_initial,
                raw_ytd_debit         = raw_debit,
                raw_ytd_credit        = raw_credit,

                parsed_initial_balance   = _parse_amount(raw_initial),
                parsed_ytd_debit         = _parse_amount(raw_debit),
                parsed_ytd_credit        = _parse_amount(raw_credit),
                parsed_balance_direction = _normalize_direction(raw_direction),

                match_status = ImportStagingStatus.PENDING_REVIEW.value,
            )
            self.db.add(staging)
            rows_loaded += 1

        session.status = ImportSessionStatus.MAPPING.value
        self.db.flush()

        return {
            "session_id":    session_id,
            "rows_loaded":   rows_loaded,
            "columns_found": columns_found,
            "header_mapping": mapping,
            "warnings":      warnings,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # 阶段三：AI 科目匹配引擎
    # ══════════════════════════════════════════════════════════════════════════

    def map_subjects(
        self,
        session_id:     int,
        tenant_id:      int,
        account_set_id: int,
    ) -> dict:
        """
        遍历 ImportStaging，分两步匹配：
          ① 编码精确匹配（无需 LLM）→ CONFIRMED
          ② 剩余行分批发 LLM 模糊匹配：
             confidence >= HIGH_CONFIDENCE → CONFIRMED（直接用 matched_code）
             confidence >= DERIVE_CONFIDENCE → 尝试智能派生子科目 → CONFIRMED 或降级
             confidence <  DERIVE_CONFIDENCE → PENDING_REVIEW
        会话状态：有 PENDING_REVIEW → REVIEWING；否则 → MAPPING（可直接结转）
        返回 {confirmed, pending_review, auto_created_subjects, skipped, session_status}
        """
        session = self._get_session(session_id, tenant_id, account_set_id)
        if session.status not in (
            ImportSessionStatus.MAPPING.value,
            ImportSessionStatus.REVIEWING.value,  # 允许重新匹配
        ):
            raise ImportSessionStatusError(
                f"会话 {session_id} 状态为 {session.status}，请先上传并清洗文件"
            )

        # 加载待匹配行
        staging_rows: list[ImportStaging] = (
            self.db.query(ImportStaging)
            .filter(
                ImportStaging.session_id     == session_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
                ImportStaging.match_status   == ImportStagingStatus.PENDING_REVIEW.value,
            )
            .all()
        )

        if not staging_rows:
            return {
                "session_id":            session_id,
                "confirmed":             0,
                "pending_review":        0,
                "auto_created_subjects": 0,
                "skipped":               0,
                "session_status":        session.status,
            }

        # 加载系统科目树（非软删除）
        tenant_subjects: list[TenantSubject] = (
            self.db.query(TenantSubject)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.is_deleted.is_(False),
            )
            .all()
        )
        subject_map: dict[str, TenantSubject] = {
            s.subject_code: s for s in tenant_subjects
        }

        # 系统科目 JSON（给 LLM 的上下文）
        system_subjects_for_llm = [
            {
                "subject_code":      s.subject_code,
                "subject_name":      s.subject_name,
                "balance_direction": s.balance_direction,
                "category":          s.category,
            }
            for s in tenant_subjects
        ]

        confirmed             = 0
        pending_review        = 0
        auto_created_subjects = 0
        skipped               = 0

        # ── Step 1: 编码精确匹配（O(1) 查表，无需 LLM）──────────────────────
        needs_llm: list[ImportStaging] = []
        for row in staging_rows:
            code = (row.raw_subject_code or "").strip()
            if not code and not (row.raw_subject_name or "").strip():
                # 无编码无名称 → 直接跳过
                row.match_status = ImportStagingStatus.SKIPPED.value
                row.skip_reason  = "科目编码和名称均为空"
                skipped += 1
                continue

            if code and code in subject_map:
                row.match_status      = ImportStagingStatus.CONFIRMED.value
                row.match_confidence  = 1.0
                row.system_subject_code = code
                row.ai_suggestions    = [{"code": code,
                                          "name": subject_map[code].subject_name,
                                          "confidence": 1.0}]
                confirmed += 1
            else:
                needs_llm.append(row)

        self.db.flush()

        # ── Step 2: LLM 模糊匹配（分批） ─────────────────────────────────────
        llm = LLMClient()
        svc_subject = SubjectService(self.db)

        for batch_start in range(0, len(needs_llm), SUBJECT_MATCH_BATCH):
            batch = needs_llm[batch_start: batch_start + SUBJECT_MATCH_BATCH]

            to_match_payload = [
                {
                    "staging_id": r.id,
                    "raw_code":   r.raw_subject_code or "",
                    "raw_name":   r.raw_subject_name or "",
                }
                for r in batch
            ]

            match_input = json.dumps(
                {
                    "to_match":       to_match_payload,
                    "system_subjects": system_subjects_for_llm,
                },
                ensure_ascii=False,
            )

            try:
                raw_result   = llm.match_subjects(match_input)
                llm_results: dict = json.loads(raw_result)
                results_list: list[dict] = llm_results.get("results", [])
            except (LLMClientError, json.JSONDecodeError) as exc:
                logger.warning("LLM 科目匹配失败（批次 %d）：%s", batch_start, exc)
                # 整批降级为 PENDING_REVIEW，不中断
                for row in batch:
                    row.ai_suggestions = None
                    pending_review += 1
                continue

            # 建立 staging_id → 行 的快速查找
            batch_map: dict[int, ImportStaging] = {r.id: r for r in batch}

            for result in results_list:
                sid        = result.get("staging_id")
                confidence = float(result.get("confidence", 0.0))
                matched    = str(result.get("matched_code", "")).strip()
                can_derive = bool(result.get("can_derive_as_child", False))
                suggestions = result.get("suggestions", [])

                row = batch_map.get(sid)
                if row is None:
                    continue

                row.match_confidence = confidence
                row.ai_suggestions   = suggestions[:3]

                if confidence >= HIGH_CONFIDENCE:
                    # 高置信度：直接确认，使用 matched_code
                    row.match_status        = ImportStagingStatus.CONFIRMED.value
                    row.system_subject_code = matched
                    confirmed += 1

                elif confidence >= DERIVE_CONFIDENCE and can_derive:
                    # 中置信度且可派生：尝试创建子科目
                    raw_code = (row.raw_subject_code or "").strip()
                    raw_name = (row.raw_subject_name or "").strip() or raw_code
                    parent   = subject_map.get(matched)
                    derived  = False

                    if parent and raw_code and raw_code not in subject_map:
                        try:
                            new_subj = SubjectCreate(
                                subject_code      = raw_code,
                                subject_name      = raw_name,
                                parent_code       = matched,
                                category          = parent.category,
                                balance_direction = (
                                    row.parsed_balance_direction
                                    or parent.balance_direction
                                ),
                                node_features     = NodeFeatures(),
                                sort_order        = 0,
                            )
                            created = svc_subject.create_subject(
                                tenant_id, account_set_id, new_subj
                            )
                            subject_map[raw_code] = created  # 更新本地缓存
                            row.match_status        = ImportStagingStatus.CONFIRMED.value
                            row.system_subject_code = raw_code
                            auto_created_subjects  += 1
                            confirmed              += 1
                            derived = True
                        except (SubjectCodeConflictError, SubjectCodeRuleError, Exception) as exc:
                            logger.info(
                                "智能派生科目 %s 失败，降级 PENDING_REVIEW：%s",
                                raw_code, exc,
                            )

                    if not derived:
                        row.match_status        = ImportStagingStatus.PENDING_REVIEW.value
                        row.system_subject_code = None
                        pending_review         += 1

                else:
                    # 低置信度：人工复核
                    row.match_status        = ImportStagingStatus.PENDING_REVIEW.value
                    row.system_subject_code = None
                    pending_review         += 1

            # 处理 LLM 未返回结果的行（保留 PENDING_REVIEW）
            returned_ids = {r.get("staging_id") for r in results_list}
            for row in batch:
                if row.id not in returned_ids:
                    pending_review += 1

        self.db.flush()

        # 更新会话状态
        if pending_review > 0:
            session.status = ImportSessionStatus.REVIEWING.value
        else:
            session.status = ImportSessionStatus.MAPPING.value

        return {
            "session_id":            session_id,
            "confirmed":             confirmed,
            "pending_review":        pending_review,
            "auto_created_subjects": auto_created_subjects,
            "skipped":               skipped,
            "session_status":        session.status,
        }

    def get_abnormal_subjects(
        self,
        session_id:     int,
        tenant_id:      int,
        account_set_id: int,
    ) -> list[dict]:
        """返回 PENDING_REVIEW 的行及 AI 建议，供前端复核工作台展示。"""
        self._get_session(session_id, tenant_id, account_set_id)

        rows: list[ImportStaging] = (
            self.db.query(ImportStaging)
            .filter(
                ImportStaging.session_id     == session_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
                ImportStaging.match_status   == ImportStagingStatus.PENDING_REVIEW.value,
            )
            .order_by(ImportStaging.row_number)
            .all()
        )

        return [
            {
                "staging_id":    r.id,
                "row_number":    r.row_number,
                "raw_code":      r.raw_subject_code,
                "raw_name":      r.raw_subject_name,
                "ai_suggestions": r.ai_suggestions or [],
            }
            for r in rows
        ]

    def confirm_subject(
        self,
        staging_id:     int,
        tenant_id:      int,
        account_set_id: int,
        subject_code:   str,
    ) -> ImportStaging:
        """人工指定科目编码，将该行状态置为 CONFIRMED。"""
        row = (
            self.db.query(ImportStaging)
            .filter(
                ImportStaging.id             == staging_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
            )
            .first()
        )
        if row is None:
            raise ImportStagingNotFoundError(f"暂存行 {staging_id} 不存在")

        # 校验科目编码在系统中存在
        exists = (
            self.db.query(TenantSubject.id)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.subject_code   == subject_code,
                TenantSubject.is_deleted.is_(False),
            )
            .first()
        )
        if not exists:
            raise ValueError(f"系统科目编码 '{subject_code}' 不存在，请先创建该科目")

        row.match_status        = ImportStagingStatus.CONFIRMED.value
        row.system_subject_code = subject_code
        row.match_confidence    = 1.0
        self.db.flush()

        # 若会话无剩余 PENDING_REVIEW，自动退出 REVIEWING 状态
        self._try_exit_reviewing(row.session_id, tenant_id, account_set_id)
        return row

    def skip_subject(
        self,
        staging_id:     int,
        tenant_id:      int,
        account_set_id: int,
        reason:         str | None,
    ) -> ImportStaging:
        """人工跳过该行（不导入），状态置为 SKIPPED。"""
        row = (
            self.db.query(ImportStaging)
            .filter(
                ImportStaging.id             == staging_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
            )
            .first()
        )
        if row is None:
            raise ImportStagingNotFoundError(f"暂存行 {staging_id} 不存在")

        row.match_status = ImportStagingStatus.SKIPPED.value
        row.skip_reason  = reason or "人工跳过"
        self.db.flush()

        self._try_exit_reviewing(row.session_id, tenant_id, account_set_id)
        return row

    def _try_exit_reviewing(
        self,
        session_id:     int,
        tenant_id:      int,
        account_set_id: int,
    ) -> None:
        """如果会话没有剩余 PENDING_REVIEW 行，自动将状态从 REVIEWING 退回 MAPPING。"""
        remaining = (
            self.db.query(ImportStaging.id)
            .filter(
                ImportStaging.session_id     == session_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
                ImportStaging.match_status   == ImportStagingStatus.PENDING_REVIEW.value,
            )
            .first()
        )
        if remaining is None:
            session = (
                self.db.query(ImportSession)
                .filter(ImportSession.session_id == session_id)
                .first()
            )
            if session and session.status == ImportSessionStatus.REVIEWING.value:
                session.status = ImportSessionStatus.MAPPING.value

    # ══════════════════════════════════════════════════════════════════════════
    # 阶段四：正式结转落库
    # ══════════════════════════════════════════════════════════════════════════

    def execute_import(
        self,
        session_id:     int,
        tenant_id:      int,
        account_set_id: int,
    ) -> dict:
        """
        1. 校验无 PENDING_REVIEW 行残留
        2. 将所有 CONFIRMED 行转换为 InitialBalance 记录（调用已有 save_balance）
        3. 调用 complete_account_setup() — 试算平衡 + 1901 海绵 + 账套 ACTIVE
        4. 会话状态 → COMPLETED
        返回 {imported, skipped, was_balanced, sponge_amount, errors}
        """
        session = self._get_session(session_id, tenant_id, account_set_id)

        if session.status not in (
            ImportSessionStatus.MAPPING.value,
            ImportSessionStatus.REVIEWING.value,
        ):
            raise ImportSessionStatusError(
                f"会话 {session_id} 状态为 {session.status}，无法执行结转"
            )

        # 检查是否存在未处理的 PENDING_REVIEW 行
        pending = (
            self.db.query(ImportStaging.id)
            .filter(
                ImportStaging.session_id     == session_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
                ImportStaging.match_status   == ImportStagingStatus.PENDING_REVIEW.value,
            )
            .first()
        )
        if pending:
            raise ImportSessionStatusError(
                "存在未处理的科目映射（PENDING_REVIEW），请先完成人工复核"
            )

        # 加载系统科目（用于获取 balance_direction）
        subject_map: dict[str, TenantSubject] = {
            s.subject_code: s
            for s in self.db.query(TenantSubject)
            .filter(
                TenantSubject.tenant_id      == tenant_id,
                TenantSubject.account_set_id == account_set_id,
                TenantSubject.is_deleted.is_(False),
            )
            .all()
        }

        # 加载 CONFIRMED 行
        confirmed_rows: list[ImportStaging] = (
            self.db.query(ImportStaging)
            .filter(
                ImportStaging.session_id     == session_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
                ImportStaging.match_status   == ImportStagingStatus.CONFIRMED.value,
            )
            .order_by(ImportStaging.row_number)
            .all()
        )
        skipped_count = (
            self.db.query(ImportStaging.id)
            .filter(
                ImportStaging.session_id     == session_id,
                ImportStaging.tenant_id      == tenant_id,
                ImportStaging.account_set_id == account_set_id,
                ImportStaging.match_status   == ImportStagingStatus.SKIPPED.value,
            )
            .count()
        )

        ib_svc = InitialBalanceService(self.db)
        imported = 0
        errors:  list[dict] = []

        for row in confirmed_rows:
            code = row.system_subject_code
            if not code:
                errors.append({"staging_id": row.id, "reason": "system_subject_code 为空"})
                continue

            subj = subject_map.get(code)
            if subj is None:
                errors.append({
                    "staging_id": row.id,
                    "reason":     f"系统科目 '{code}' 不存在，可能已被删除",
                })
                continue

            # 余额方向优先取 staging 解析值，回退到科目默认方向
            direction = row.parsed_balance_direction or subj.balance_direction

            try:
                ib_input = InitialBalanceInput(
                    subject_code      = code,
                    balance_direction = direction,
                    initial_balance   = row.parsed_initial_balance or 0.0,
                    ytd_debit         = row.parsed_ytd_debit        or 0.0,
                    ytd_credit        = row.parsed_ytd_credit       or 0.0,
                    auxiliary_details = [],
                )
                ib_svc.save_balance(tenant_id, account_set_id, ib_input)
                imported += 1
            except Exception as exc:
                errors.append({"staging_id": row.id, "reason": str(exc)})

        if imported > 0:
            self.db.flush()

        # 调用海绵结转（试算平衡 + 1901 兜底 + 账套 ACTIVE）
        complete_result = ib_svc.complete_account_setup(tenant_id, account_set_id)

        session.status = ImportSessionStatus.COMPLETED.value
        self.db.flush()

        return {
            "session_id":    session_id,
            "imported":      imported,
            "skipped":       skipped_count,
            "was_balanced":  complete_result.was_balanced,
            "sponge_amount": float(complete_result.sponge_amount),
            "errors":        errors,
        }
