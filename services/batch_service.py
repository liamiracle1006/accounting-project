"""
AgentLedger V4.0 — 批处理服务（三色漏斗异步引擎）(Sprint 3.5)

职责：
  create_batch_task()    — 创建 BatchImportTask + BatchImportRecord，状态 PENDING
  run_batch_pipeline()   — 后台三色漏斗主引擎（由 BackgroundTasks 调用）

三色分流逻辑：
  🟢 HIGH   → needs_review=False，正常 DRAFT 状态入库
  🟡 MEDIUM/LOW → needs_review=True，同样入库，前端 UI 标黄
  🔴 Exception  → error_msg 写入 BatchImportRecord，跳过凭证生成

安全设计（与 Sprint 3.4 habit_service.py 保持一致）：
  - run_batch_pipeline 内部实例化独立 SessionLocal()，绝不复用路由层 Session
  - tenant_id / account_set_id / creator_id 全部显式传参，不依赖 ContextVar
  - 单条记录失败 → db.rollback() 隔离，绝不导致整批事务回滚
  - LLM 调用之间 time.sleep(0.5) 防止 API 速率限制（HTTP 429）
  - 整批流水线崩溃（极端情况）→ task.status = FAILED，不抛出给调用方
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.batch_task import BatchImportTask, BatchImportRecord, TaskStatus
from schemas.batch_schemas import StandardReceiptItem

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 公开方法
# ══════════════════════════════════════════════════════════════════════════════

def create_batch_task(
    db:             Session,
    tenant_id:      int,
    account_set_id: int,
    items:          list[StandardReceiptItem],
    creator_id:     Optional[int],
) -> BatchImportTask:
    """
    在数据库中创建 BatchImportTask + 所有 BatchImportRecord（状态 PENDING）。
    调用方负责 db.commit()。
    """
    task = BatchImportTask(
        tenant_id           = tenant_id,
        account_set_id      = account_set_id,
        status              = TaskStatus.PENDING,
        total_count         = len(items),
        success_count       = 0,
        error_count         = 0,
        needs_review_count  = 0,
        creator_id          = creator_id,
    )
    db.add(task)
    db.flush()   # 获取 task_id

    for item in items:
        record = BatchImportRecord(
            tenant_id      = tenant_id,
            account_set_id = account_set_id,
            task_id        = task.task_id,
            raw_data       = item.model_dump_json(),
        )
        db.add(record)

    db.flush()
    logger.info(
        "create_batch_task: task_id=%d total=%d tenant=%d",
        task.task_id, len(items), tenant_id,
    )
    return task


def run_batch_pipeline(
    task_id:        int,
    tenant_id:      int,
    account_set_id: int,
    creator_id:     Optional[int],
    voucher_word:   str = "记",
) -> None:
    """
    批处理主引擎（后台异步执行）。

    由 POST /api/batch/execute 通过 FastAPI BackgroundTasks 触发。
    使用独立 DB Session，所有参数显式传入（不依赖任何 ContextVar）。
    任何致命异常均被捕获并标记 task.status=FAILED，绝不上浮。
    """
    from database.connection import SessionLocal

    db = SessionLocal()
    try:
        _run_pipeline_inner(db, task_id, tenant_id, account_set_id, creator_id, voucher_word)
    except Exception as exc:
        logger.error("run_batch_pipeline fatal task_id=%d: %s", task_id, exc)
        try:
            task = db.get(BatchImportTask, task_id)
            if task:
                task.status     = TaskStatus.FAILED
                task.updated_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 内部实现
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline_inner(
    db:             Session,
    task_id:        int,
    tenant_id:      int,
    account_set_id: int,
    creator_id:     Optional[int],
    voucher_word:   str,
) -> None:
    # 延迟导入，防止循环依赖
    from services.ai_voucher_service import AIVoucherService
    from services.voucher_service import VoucherService
    from schemas.voucher_ai_schemas import (
        ConfirmLineIn,
        ConfirmVoucherInput,
        GenerateVoucherInput,
    )

    # ── 1. 标记 PROCESSING ────────────────────────────────────────────────────
    task = db.get(BatchImportTask, task_id)
    if task is None:
        logger.error("_run_pipeline_inner: task_id=%d not found", task_id)
        return

    task.status     = TaskStatus.PROCESSING
    task.updated_at = datetime.now(timezone.utc)
    db.commit()

    # ── 2. 仅取记录 ID 列表（避免后续 rollback 使 ORM 对象失效）────────────────
    record_ids: list[int] = [
        row[0]
        for row in db.execute(
            select(BatchImportRecord.id).where(BatchImportRecord.task_id == task_id)
        ).all()
    ]

    success_count      = 0
    error_count        = 0
    needs_review_count = 0

    # ── 3. 逐条三色漏斗处理 ───────────────────────────────────────────────────
    for i, record_id in enumerate(record_ids):
        if i > 0:
            time.sleep(0.5)   # ← 防止大模型 API 速率限制（HTTP 429）

        try:
            record = db.get(BatchImportRecord, record_id)
            if record is None:
                continue

            item = StandardReceiptItem.model_validate_json(record.raw_data)

            # ── 关键：将结构化 amount 拼入 description，
            #    解决 AIVoucherService._extract_amount() 正则无法从纯文字里提取金额的冲突 ──
            description = f"{item.summary} {item.amount}元"
            if item.counterparty:
                description = f"{item.counterparty} {description}"

            body = GenerateVoucherInput(
                description  = description,
                voucher_date = item.date,
            )

            # ── 双轨推荐（Track A 历史习惯 + Track B LLM 兜底）────────────────
            ai_svc   = AIVoucherService(db)
            response = ai_svc.generate_voucher(body, tenant_id, account_set_id)

            # ── 取首位推荐的置信度
            #    Track A 存在 → recommendations[0] 就是 Track A
            #    冷启动 → recommendations[0] 是 Track B，confidence 天然为 LOW ──
            best       = response.recommendations[0]
            confidence = best.confidence
            draft      = best.draft

            # ── 构建确认入账请求体 ─────────────────────────────────────────────
            confirm_body = ConfirmVoucherInput(
                description  = description,
                voucher_date = item.date,
                voucher_word = voucher_word,
                memo         = draft.memo,
                lines        = [
                    ConfirmLineIn(
                        subject_code   = line.subject_code,
                        direction      = line.direction,
                        amount         = line.amount,
                        memo           = line.memo,
                        auxiliary_data = line.auxiliary_data,
                    )
                    for line in draft.lines
                ],
                habit_rule_id = best.habit_rule_id,
            )

            # ── 持久化凭证 ────────────────────────────────────────────────────
            v_svc = VoucherService(db)
            vh    = v_svc.confirm_ai_draft(
                tenant_id, account_set_id, confirm_body, creator_id=creator_id
            )
            db.flush()

            # ── 更新记录状态并提交 ──────────────────────────────────────────────
            record.voucher_id   = vh.voucher_id
            record.confidence   = confidence
            record.needs_review = confidence in ("MEDIUM", "LOW")
            db.commit()

            success_count += 1
            if record.needs_review:
                needs_review_count += 1

            logger.info(
                "batch ✓ record_id=%d voucher_id=%d confidence=%s needs_review=%s",
                record_id, vh.voucher_id, confidence, record.needs_review,
            )

        except Exception as exc:
            # ── 🔴 红灯：单条失败，回滚并写入 error_msg，不影响其余记录 ──────────
            db.rollback()
            error_count += 1
            logger.warning("batch ✗ record_id=%d: %s", record_id, exc)

            try:
                # rollback 后重新取对象
                record = db.get(BatchImportRecord, record_id)
                if record:
                    record.error_msg = str(exc)[:500]
                    db.commit()
            except Exception as inner_exc:
                logger.warning(
                    "batch: error_msg 写入失败 record_id=%d: %s", record_id, inner_exc
                )
                try:
                    db.rollback()
                except Exception:
                    pass

    # ── 4. 更新任务最终统计 ───────────────────────────────────────────────────
    task = db.get(BatchImportTask, task_id)
    if task:
        task.status             = TaskStatus.COMPLETED
        task.success_count      = success_count
        task.error_count        = error_count
        task.needs_review_count = needs_review_count
        task.updated_at         = datetime.now(timezone.utc)
        db.commit()

    logger.info(
        "batch COMPLETED task_id=%d: success=%d error=%d needs_review=%d",
        task_id, success_count, error_count, needs_review_count,
    )
