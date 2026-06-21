"""Admin-only audit log query endpoints."""
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, and_
from sqlalchemy.orm import Session

from app.auth import require_admin, CurrentUser
from app.database import get_db
from app.models.financial import AuditLog

router = APIRouter()


class AuditLogOut(BaseModel):
    id: int
    username: str | None
    ledger_id: int | None
    method: str
    path: str
    status_code: int
    detail: dict | None
    ip_address: str | None
    duration_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    page_size: int


@router.get("/audit-logs", response_model=AuditLogPage)
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    username: Optional[str] = Query(None, description="Filter by username"),
    method: Optional[str] = Query(None, description="Filter by HTTP method"),
    ledger_id: Optional[int] = Query(None, description="Filter by ledger"),
    status_code: Optional[int] = Query(None, description="Filter by HTTP status code"),
    date_from: Optional[date] = Query(None, description="Start date (inclusive)"),
    date_to: Optional[date] = Query(None, description="End date (inclusive)"),
    path_contains: Optional[str] = Query(None, description="Partial path match"),
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(require_admin),
):
    query = db.query(AuditLog)

    filters = []
    if username:
        filters.append(AuditLog.username == username)
    if method:
        filters.append(AuditLog.method == method.upper())
    if ledger_id is not None:
        filters.append(AuditLog.ledger_id == ledger_id)
    if status_code is not None:
        filters.append(AuditLog.status_code == status_code)
    if date_from:
        filters.append(AuditLog.created_at >= date_from)
    if date_to:
        filters.append(AuditLog.created_at < date_to + timedelta(days=1))  # inclusive end date
    if path_contains:
        filters.append(AuditLog.path.contains(path_contains))

    if filters:
        query = query.filter(and_(*filters))

    total = query.count()
    items = (
        query.order_by(desc(AuditLog.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return AuditLogPage(
        items=[AuditLogOut.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
