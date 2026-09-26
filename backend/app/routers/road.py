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


# 注意：/export、/stats 这类静态路径必须声明在 /{entry_id} 之前，
# 否则 FastAPI 会把 export、stats 当成 entry_id 解析，整数转换失败直接 422。
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出道路设施清单：返回全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "road", "total": total, "items": items}


@router.get("/stats")
def stats() -> dict[str, Any]:
    """统计概要：在养道路、重点观测道路、管养里程。"""
    return service.stats()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="兼容入口：按设施编码或道路名称模糊检索"),
    code: str | None = Query(default=None, description="按设施编码模糊检索"),
    name: str | None = Query(default=None, description="按道路名称模糊检索"),
    grade: str | None = Query(default=None, description="按道路等级模糊检索"),
    status: str | None = Query(default=None, description="待移交、正常养护、重点观测、封闭施工"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按设施编码、道路名称、道路等级与状态过滤道路设施列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword,
        code=code,
        name=name,
        grade=grade,
        status=status,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条道路设施明细（含操作记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"道路设施 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条道路设施，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="道路设施已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条道路设施执行办理移交、标记观测、封闭设施；不允许的动作会被拦下并说明原因（哪一头不允许）。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
