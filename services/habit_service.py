"""
AgentLedger V4.0 — HabitService：动态分叉学习算法 (Sprint 3.4)

核心方法：
  learn_from_voucher_async(voucher_id, habit_rule_id, description)

    由 /confirm 端点的 BackgroundTask 异步调用，在凭证入库后更新 DAG 规则。
    使用独立 DB Session，绝不复用路由层的 Session，避免生命周期冲突。

两条学习路径：
  路径 A（habit_rule_id 不为 None）：用户选择了历史习惯推荐（Track A）
    → 精准找到对应规则，更新 edge
    → 命中已有 edge：weight +1，扩宽金额区间
    → 未命中（新科目组合）：在同一规则下 append 新 edge（绝不覆盖旧 edge）

  路径 B（habit_rule_id 为 None）：用户确认了 AI 推断（Track B）
    → 从描述提取关键词，查找是否有关键词重叠的现有规则
    → 有重叠：复用旧规则，更新/新增 edge
    → 无重叠：自动创建全新 TenantHabitRule，从零开始学习

安全设计：
  - 所有异常均被 try-except 吞掉，绝不阻塞主流程凭证保存
  - 用自己的 SessionLocal() 开连接，finally 里确保 close()
"""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# 公开入口（由 BackgroundTasks 调用）
# ══════════════════════════════════════════════════════════════════════════════

def learn_from_voucher_async(
    voucher_id:    int,
    habit_rule_id: Optional[int],
    description:   str,
) -> None:
    """
    凭证入库后的异步学习钩子。

    参数：
      voucher_id    — 刚入库的凭证 ID（VoucherHeader.voucher_id）
      habit_rule_id — 用户选了 Track A 时不为 None，选了 Track B 时为 None
      description   — 原始业务描述（用于 Track B 路径的关键词提取）
    """
    # 延迟导入，避免循环依赖（service 层互相引用）
    from database.connection import SessionLocal

    db = SessionLocal()
    try:
        _do_learn(db, voucher_id, habit_rule_id, description)
        db.commit()
    except Exception as exc:
        logger.warning(
            "learn_from_voucher_async failed voucher_id=%d: %s", voucher_id, exc
        )
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# 内部核心逻辑
# ══════════════════════════════════════════════════════════════════════════════

def _do_learn(
    db:            Session,
    voucher_id:    int,
    habit_rule_id: Optional[int],
    description:   str,
) -> None:
    """
    执行实际的学习逻辑。由 learn_from_voucher_async 包装，统一处理事务。
    """
    from models.voucher_header import VoucherHeader
    from models.voucher_line import VoucherLine

    # ── 1. 取凭证数据 ─────────────────────────────────────────────────────────
    vh = db.get(VoucherHeader, voucher_id)
    if vh is None:
        logger.warning("learn: voucher_id=%d 不存在，跳过学习", voucher_id)
        return

    lines = (
        db.query(VoucherLine)
        .filter(VoucherLine.voucher_id == voucher_id)
        .all()
    )
    if not lines:
        logger.warning("learn: voucher_id=%d 无分录行，跳过学习", voucher_id)
        return

    total_amount = float(vh.total_amount or 0)
    if total_amount <= 0:
        logger.warning("learn: voucher_id=%d total_amount=%s，跳过学习", voucher_id, vh.total_amount)
        return

    # ── 2. 提取特征 ───────────────────────────────────────────────────────────
    subject_combo = [f"{l.subject_code}-{l.direction}" for l in lines]
    line_templates = [
        {
            "subject_code": l.subject_code,
            "direction":    l.direction,
            "ratio":        round(float(l.amount) / total_amount, 6),
            "memo_hint":    l.memo,
        }
        for l in lines
    ]
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 3. 路径分叉 ───────────────────────────────────────────────────────────
    if habit_rule_id is not None:
        _learn_track_a(db, habit_rule_id, subject_combo, line_templates, total_amount, now_iso)
    else:
        _learn_track_b(
            db,
            vh        = vh,
            description    = description,
            subject_combo  = subject_combo,
            line_templates = line_templates,
            total_amount   = total_amount,
            now_iso        = now_iso,
        )


def _learn_track_a(
    db:            Session,
    habit_rule_id: int,
    subject_combo: list[str],
    line_templates: list[dict],
    total_amount:  float,
    now_iso:       str,
) -> None:
    """
    Track A 学习：精准更新指定规则的 DAG edge。

    命中已有 edge（科目组合完全一致）：
      weight +1，扩宽金额区间，刷新 last_used_at

    未命中（全新科目组合）：
      在同一规则下 append 新 edge，weight=1
      绝不删除/覆盖已有 edge（新枝发芽，旧枝保留）
    """
    from models.tenant_habit_rule import TenantHabitRule

    rule = db.get(TenantHabitRule, habit_rule_id)
    if rule is None:
        logger.warning("learn_track_a: habit_rule_id=%d 不存在，跳过", habit_rule_id)
        return

    try:
        dag = json.loads(rule.rule_json)
    except json.JSONDecodeError:
        logger.warning("learn_track_a: rule_id=%d rule_json 解析失败，跳过", habit_rule_id)
        return

    edges = dag.get("edges", [])

    # 用集合比较，顺序无关
    subject_set = set(subject_combo)
    matched_edge = None
    for edge in edges:
        cf = edge.get("context_features", {})
        if set(cf.get("subject_combo", [])) == subject_set:
            matched_edge = edge
            break

    if matched_edge is not None:
        # ── 命中：weight++ + 扩宽金额区间 ────────────────────────────────────
        matched_edge["weight"]       = matched_edge.get("weight", 1) + 1
        matched_edge["last_used_at"] = now_iso
        cf = matched_edge.setdefault("context_features", {})
        cf["min_amount"]    = min(cf.get("min_amount", total_amount), total_amount)
        cf["max_amount"]    = max(cf.get("max_amount", total_amount), total_amount)
        cf["subject_combo"] = subject_combo
        cf["line_templates"] = line_templates
        logger.info(
            "learn_track_a: rule_id=%d edge hit，weight=%d",
            habit_rule_id, matched_edge["weight"],
        )
    else:
        # ── 未命中：新枝发芽，追加 edge ───────────────────────────────────────
        new_edge = {
            "from":          "LEARNED",
            "to":            "LEARNED",
            "condition":     f"学习自 {now_iso[:10]}",
            "weight":        1,
            "last_used_at":  now_iso,
            "context_features": {
                "subject_combo":  subject_combo,
                "line_templates": line_templates,
                "min_amount":     total_amount,
                "max_amount":     total_amount,
            },
        }
        edges.append(new_edge)
        dag["edges"] = edges
        logger.info(
            "learn_track_a: rule_id=%d 新分支，当前 edges=%d 条",
            habit_rule_id, len(edges),
        )

    rule.rule_json = json.dumps(dag, ensure_ascii=False)


def _learn_track_b(
    db:            Session,
    vh,            # VoucherHeader ORM 对象（避免循环 import 用 Any）
    description:   str,
    subject_combo: list[str],
    line_templates: list[dict],
    total_amount:  float,
    now_iso:       str,
) -> None:
    """
    Track B 学习：用户确认了 AI 推断（无历史规则）。

    1. 从描述提取关键词
    2. 扫描现有规则，看是否有关键词重叠的规则
       - 有重叠：复用该规则，更新/新增 edge
       - 无重叠：自动创建全新 TenantHabitRule
    """
    from models.tenant_habit_rule import TenantHabitRule

    keywords = _extract_keywords(description)
    if not keywords:
        logger.warning("learn_track_b: 描述提取不到关键词，跳过: %s", description[:30])
        return

    # ── 查找关键词有重叠的现有规则 ────────────────────────────────────────────
    existing_rules = (
        db.query(TenantHabitRule)
        .filter(
            TenantHabitRule.tenant_id      == vh.tenant_id,
            TenantHabitRule.account_set_id == vh.account_set_id,
            TenantHabitRule.is_active      == True,
        )
        .all()
    )

    kw_set = set(keywords)
    overlapping_rule = None
    for rule in existing_rules:
        try:
            existing_kws = set(json.loads(rule.keywords))
        except Exception:
            continue
        if kw_set & existing_kws:   # 有交集
            overlapping_rule = rule
            break

    if overlapping_rule is not None:
        # ── 复用旧规则，更新 edge ─────────────────────────────────────────────
        logger.info(
            "learn_track_b: 关键词命中旧规则 id=%d，更新 edge", overlapping_rule.id
        )
        _learn_track_a(
            db, overlapping_rule.id,
            subject_combo, line_templates, total_amount, now_iso,
        )
    else:
        # ── 全新规则：自动创建 ────────────────────────────────────────────────
        new_dag = {
            "nodes": [{
                "id":           "LEARNED",
                "label":        description[:30],
                "subject_hint": "",
                "action":       "AI 自动学习",
            }],
            "edges": [{
                "from":         "LEARNED",
                "to":           "LEARNED",
                "condition":    f"AI 推断 {now_iso[:10]}",
                "weight":       1,
                "last_used_at": now_iso,
                "context_features": {
                    "subject_combo":  subject_combo,
                    "line_templates": line_templates,
                    "min_amount":     total_amount,
                    "max_amount":     total_amount,
                },
            }],
        }
        new_rule = TenantHabitRule(
            tenant_id      = vh.tenant_id,
            account_set_id = vh.account_set_id,
            rule_name      = description[:40],
            description    = f"AI 自动学习（{now_iso[:10]}）",
            keywords       = json.dumps(keywords, ensure_ascii=False),
            rule_json      = json.dumps(new_dag, ensure_ascii=False),
            is_active      = True,
        )
        db.add(new_rule)
        logger.info(
            "learn_track_b: 自动创建新规则 '%s'，keywords=%s",
            new_rule.rule_name, keywords,
        )


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _extract_keywords(description: str) -> list[str]:
    """
    从业务描述中提取 2-4 个中文关键词（2-6 字的连续汉字片段）。
    去重保序，最多返回 4 个。
    """
    cn_words = re.findall(r'[\u4e00-\u9fff]{2,6}', description)
    seen: set[str] = set()
    result: list[str] = []
    for w in cn_words:
        if w not in seen:
            seen.add(w)
            result.append(w)
        if len(result) >= 4:
            break

    # 兜底：取前 10 个字符
    if not result:
        short = description[:10].strip()
        if short:
            result = [short]

    return result
