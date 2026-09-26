"""道路设施业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "road"
REQUIRED_FIELDS = ["设施编码", "道路名称", "道路等级"]
STATUS_ORDER = ["待移交", "正常养护", "重点观测", "封闭施工"]
STATUS_FIELD = "设施状态"
# 每个动作只允许在指定的现状下办理；现状不在 sources 里就回绝，并说明是哪一头不允许。
ACTION_RULES: dict[str, dict[str, Any]] = {
    "办理移交": {"sources": ("待移交",), "target": "正常养护"},
    "标记观测": {"sources": ("正常养护",), "target": "重点观测"},
    "封闭设施": {"sources": ("重点观测",), "target": "封闭施工"},
}
STAT_CARDS = ["在养道路", "重点观测道路", "管养里程"]


class RoadService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        name: str | None = None,
        level: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        keyword = (keyword or "").strip()
        name = (name or "").strip()
        level = (level or "").strip()
        status = (status or "").strip()
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("设施编码", ""))]
        if name:
            rows = [row for row in rows if name in str(row.get("道路名称", ""))]
        if level:
            rows = [row for row in rows if level in str(row.get("道路等级", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> list[dict[str, Any]]:
        """统计概要：在养与重点观测按状态机计数，管养里程用在册设施总量。"""
        rows = store.rows(MODULE)
        return [
            {"label": "在养道路", "value": sum(1 for row in rows if row.get("status") == "正常养护")},
            {"label": "重点观测道路", "value": sum(1 for row in rows if row.get("status") == "重点观测")},
            {"label": "管养里程", "value": len(rows)},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记道路设施。成功返回 (记录, 提示语)；缺字段或重复提交时返回 (None, 原因)。"""
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values.get("设施编码")).strip()
        # 同一设施编码重复提交只认既有那一条，不再生成第二条记录，也不动其它设施的状态。
        for row in store.rows(MODULE):
            if str(row.get("设施编码", "")).strip() == code:
                return None, f"设施编码「{code}」已登记（记录 #{row.get('id')}），同一设施重复提交不会再生成记录"
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        self._apply_status(entry, STATUS_ORDER[0])
        rows.append(entry)
        return entry, "道路设施已登记"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"道路设施 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            allowed = "、".join(ACTION_RULES)
            return None, f"动作「{action}」不属于道路设施可执行范围（可执行：{allowed}）"
        rule = ACTION_RULES[action]
        current = str(entry.get("status", ""))
        if current not in rule["sources"]:
            expect = "、".join(rule["sources"])
            return None, (
                f"当前状态「{current}」不允许执行「{action}」，该动作仅允许在「{expect}」状态办理"
            )
        self._apply_status(entry, rule["target"])
        return entry, f"道路设施已{action}"

    def _apply_status(self, entry: dict[str, Any], status: str) -> None:
        """状态机字段与列表里的「设施状态」展示字段同步落库，回执与清单才对得上号。"""
        entry["status"] = status
        entry[STATUS_FIELD] = status
        entry["pending"] = status != STATUS_ORDER[-1]
        entry["abnormal"] = False
