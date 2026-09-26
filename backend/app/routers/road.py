"""道路设施接口：维护道路设施，覆盖办理移交、标记观测、封闭设施等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.road import RoadService

router = APIRouter(prefix="/api/road", tags=["道路设施"])

service = RoadService()

LIST_FIELDS = ["设施编码", "道路名称", "道路等级", "起止桩号", "路面结构", "管养单位", "建成年份", "设施状态"]
STATUSES = ["待移交", "正常养护", "重点观测", "封闭施工"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按设施编码检索"),
    name: str | None = Query(default=None, description="按道路名称检索"),
    level: str | None = Query(default=None, description="按道路等级检索"),
    status: str | None = Query(default=None, description="待移交、正常养护、重点观测、封闭施工"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按设施编码、道路名称、道路等级与状态过滤道路设施列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, name=name, level=level, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def stats() -> dict[str, Any]:
    """统计概要：在养、重点观测与在册总量；动作办完后前端会重新拉取。"""
    return {"module": "road", "cards": service.stats()}


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出道路设施清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "road", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条道路设施明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"道路设施 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条道路设施；缺字段或同一设施重复提交时说明原因，不会静默生成第二条记录。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条道路设施执行办理移交、标记观测、封闭设施；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
