"""道路设施业务规则：状态流转、字段校验与筛选口径都收在这里。

状态机（只允许向前一步，终态「封闭施工」不可再流转）：

    待移交 --办理移交--> 正常养护 --标记观测--> 重点观测 --封闭设施--> 封闭施工

同一件事重复提交（当前状态已经是该动作的目标状态）不会重复落记录；
并发请求用锁串行化，保证只更新命中的那一条设施，不覆盖别的设施。
"""
from __future__ import annotations

import re
import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "road"
REQUIRED_FIELDS = ["设施编码", "道路名称", "道路等级"]
STATUS_ORDER = ["待移交", "正常养护", "重点观测", "封闭施工"]
# 每个动作只允许从哪个状态发起、流转到哪个状态
ACTION_RULES: dict[str, tuple[str, str]] = {
    "办理移交": ("待移交", "正常养护"),
    "标记观测": ("正常养护", "重点观测"),
    "封闭设施": ("重点观测", "封闭施工"),
}

# 动作锁：同一时刻只放行一个写请求，避免重复点击产生重复记录
_action_lock = threading.Lock()


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _kilometer(row: dict[str, Any]) -> float:
    """从「起止桩号」里量出管养里程（公里），认不出来按 0 计。

    支持 K3+200 这种「公里+米」写法，例如 K0+000-K3+200 记 3.2 公里；
    没有 K 桩号时退回取两个普通数字之差。
    """
    text = str(row.get("起止桩号") or "")
    stakes = [
        int(km) * 1000 + int(meter)
        for km, meter in re.findall(r"[Kk](\d+)\s*\+\s*(\d+)", text)
    ]
    if len(stakes) >= 2:
        return round(abs(stakes[1] - stakes[0]) / 1000, 3)
    numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]
    if len(numbers) >= 2:
        return round(abs(numbers[1] - numbers[0]), 3)
    return 0.0


class RoadService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        code: str | None = None,
        name: str | None = None,
        grade: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)

        def hit(value: Any, needle: str | None) -> bool:
            return needle is None or needle in str(value or "")

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if not hit(row.get("设施编码"), code):
                continue
            if not hit(row.get("道路名称"), name):
                continue
            if not hit(row.get("道路等级"), grade):
                continue
            if status is not None and row.get("status") != status:
                continue
            # keyword 兼容老入口：编码或名称命中即可
            if keyword and keyword not in str(row.get("设施编码") or "") \
                    and keyword not in str(row.get("道路名称") or ""):
                continue
            filtered.append(row)
        total = len(filtered)
        start = max(page - 1, 0) * size
        return filtered[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        with _action_lock:
            entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
            # 其余选填字段原样保留，不能丢
            for field in ("起止桩号", "路面结构", "管养单位", "建成年份"):
                if values.get(field) is not None:
                    entry[field] = values.get(field)
            entry["status"] = STATUS_ORDER[0]
            # 展示列与内部状态保持一致，列表/详情看到的就是真实状态
            entry["设施状态"] = entry["status"]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["history"] = [
                {
                    "action": "登记设施",
                    "from_status": None,
                    "to_status": entry["status"],
                    "time": _now_text(),
                    "remark": "道路设施登记入库",
                }
            ]
            rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"道路设施 {entry_id} 不存在或已归档，无法执行动作"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于道路设施可执行范围（可选：办理移交、标记观测、封闭设施）"

        allowed_from, target = ACTION_RULES[action]
        with _action_lock:
            current = entry.get("status")
            if current == target:
                # 同一件事重复提交：幂等拒绝，不新增操作记录，也不改状态
                return None, f"道路设施「{entry.get('道路名称', entry_id)}」当前已是「{target}」，动作「{action}」已处理过，请勿重复提交"
            if current != allowed_from:
                # 讲清楚是哪一头不允许：当前状态这一头不具备执行条件
                return None, (
                    f"道路设施「{entry.get('道路名称', entry_id)}」当前状态为「{current}」，"
                    f"只有「{allowed_from}」状态才允许执行「{action}」（将流转到「{target}」）"
                )
            entry["status"] = target
            entry["设施状态"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = target == "重点观测"
            history = entry.setdefault("history", [])
            history.append(
                {
                    "action": action,
                    "from_status": allowed_from,
                    "to_status": target,
                    "time": _now_text(),
                    "remark": "",
                }
            )
        return entry, f"道路设施「{entry.get('道路名称', entry_id)}」已{action}，当前状态：{target}"

    def stats(self) -> dict[str, int | float]:
        """统计概要：在养道路（除封闭施工外）、重点观测道路、管养里程（公里）。"""
        rows = store.rows(MODULE)
        maintained = [row for row in rows if row.get("status") != "封闭施工"]
        watching = sum(1 for row in rows if row.get("status") == "重点观测")
        mileage = round(sum(_kilometer(row) for row in maintained), 3)
        return {
            "maintained": len(maintained),
            "watching": watching,
            "mileage": mileage,
        }
