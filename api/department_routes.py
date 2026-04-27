"""
AgentLedger — Department API (Phase 3)

端点：
  POST   /api/departments           — 创建部门（仅 BOSS）
  GET    /api/departments           — 列出所有部门
  PUT    /api/departments/{id}      — 修改部门信息（仅 BOSS）
  DELETE /api/departments/{id}      — 停用部门（仅 BOSS，软删除）
"""
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db
from models.department import Department
from models.user_account import UserRole
from services.auth_service import get_current_user, require_role
from models.user_account import UserAccount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/departments", tags=["departments"])


# ── Schemas ────────────────────────────────────────────────────────────────────

class DeptRequest(BaseModel):
    dept_name:   str       = Field(..., min_length=1, max_length=100)
    cost_center: str | None = Field(default=None, max_length=50)
    manager_id:  int | None = None


def _dept_to_dict(d: Department) -> dict:
    return {
        "dept_id":     d.dept_id,
        "dept_name":   d.dept_name,
        "cost_center": d.cost_center,
        "manager_id":  d.manager_id,
        "is_active":   bool(d.is_active),
        "created_at":  str(d.created_at) if d.created_at else None,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_department(
    body:         DeptRequest,
    current_user: UserAccount = Depends(require_role(UserRole.BOSS)),
    db:           Session     = Depends(get_db),
) -> Any:
    if db.query(Department).filter(Department.dept_name == body.dept_name,
                                   Department.is_active == 1).first():
        raise HTTPException(status_code=409, detail=f"部门名称 '{body.dept_name}' 已存在")

    dept = Department(
        dept_name   = body.dept_name,
        cost_center = body.cost_center,
        manager_id  = body.manager_id,
        is_active   = 1,
    )
    db.add(dept)
    db.commit()
    db.refresh(dept)
    logger.info("Department created: id=%s name=%s by=%s", dept.dept_id, dept.dept_name, current_user.username)
    return _dept_to_dict(dept)


@router.get("")
def list_departments(
    current_user: UserAccount = Depends(get_current_user),
    db:           Session     = Depends(get_db),
) -> Any:
    depts = db.query(Department).filter(Department.is_active == 1).order_by(Department.dept_id).all()
    return [_dept_to_dict(d) for d in depts]


@router.put("/{dept_id}")
def update_department(
    dept_id:      int,
    body:         DeptRequest,
    current_user: UserAccount = Depends(require_role(UserRole.BOSS)),
    db:           Session     = Depends(get_db),
) -> Any:
    dept = db.get(Department, dept_id)
    if not dept or not dept.is_active:
        raise HTTPException(status_code=404, detail="部门不存在")

    dept.dept_name   = body.dept_name
    dept.cost_center = body.cost_center
    dept.manager_id  = body.manager_id
    db.commit()
    db.refresh(dept)
    return _dept_to_dict(dept)


@router.delete("/{dept_id}")
def deactivate_department(
    dept_id:      int,
    current_user: UserAccount = Depends(require_role(UserRole.BOSS)),
    db:           Session     = Depends(get_db),
) -> Any:
    dept = db.get(Department, dept_id)
    if not dept or not dept.is_active:
        raise HTTPException(status_code=404, detail="部门不存在")

    dept.is_active = 0
    db.commit()
    logger.info("Department deactivated: id=%s by=%s", dept_id, current_user.username)
    return {"ok": True, "message": f"部门 '{dept.dept_name}' 已停用"}
