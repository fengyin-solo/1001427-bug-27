"""道路设施模块回归测试：动作回执、状态机、筛选、统计与幂等。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.seed import SEED_ROWS
from app.store import store

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_store():
    """每个用例都从种子数据重新开始，避免动作互相污染。"""
    store._tables = {name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()}
    yield


def _action(entry_id: int, action: str):
    return client.post(f"/api/road/{entry_id}/actions", json={"values": {"action": action}})


def _status(entry_id: int) -> str:
    response = client.get(f"/api/road/{entry_id}")
    assert response.status_code == 200
    return response.json()["status"]


def test_action_receipt_matches_list_and_detail():
    """标记观测成功后，列表行、详情页与统计概要里的状态口径一致。"""
    result = _action(2, "标记观测")
    assert result.status_code == 200
    body = result.json()
    assert body["ok"] is True
    assert body["entry"]["status"] == "重点观测"

    detail = client.get("/api/road/2").json()
    assert detail["status"] == "重点观测"
    assert detail["设施状态"] == "重点观测"

    listed = client.get("/api/road", params={"status": "重点观测"}).json()
    assert [item["id"] for item in listed["items"]] == [2, 3]
    assert all(item["设施状态"] == "重点观测" for item in listed["items"])


def test_action_only_allowed_in_matching_state():
    """每一步只在当前状态下允许执行，被拦下时讲清是哪一头不允许。"""
    # 待移交状态不能直接标记观测
    body = _action(1, "标记观测").json()
    assert body["ok"] is False
    assert "待移交" in body["message"] and "正常养护" in body["message"]
    assert _status(1) == "待移交"

    # 正常养护状态不能跳过观测直接封闭
    body = _action(2, "封闭设施").json()
    assert body["ok"] is False
    assert "重点观测" in body["message"]
    assert _status(2) == "正常养护"

    # 不存在的动作与记录也要说清是哪一头不允许
    body = _action(2, "强行拆除").json()
    assert body["ok"] is False
    assert "不属于道路设施可执行范围" in body["message"]
    body = _action(999, "办理移交").json()
    assert body["ok"] is False
    assert "不存在" in body["message"]


def test_full_lifecycle_and_stats_refresh():
    """走完整条流转链，统计概要跟着状态一起变。"""
    assert _action(1, "办理移交").json()["ok"] is True
    assert _action(1, "标记观测").json()["ok"] is True
    assert _action(1, "封闭设施").json()["ok"] is True
    assert _status(1) == "封闭施工"

    cards = {card["label"]: card["value"] for card in client.get("/api/road/stats").json()["cards"]}
    assert cards["重点观测道路"] == 1  # 只剩种子里的 #3
    assert cards["在养道路"] == 1  # 只剩种子里的 #2
    assert cards["管养里程"] == 3


def test_close_facility_shrinks_observation_list_and_count():
    """封闭设施以后，重点观测计数减一，清单里不再出现这条已处理记录。"""
    before = {card["label"]: card["value"] for card in client.get("/api/road/stats").json()["cards"]}
    assert before["重点观测道路"] == 1

    assert _action(3, "封闭设施").json()["ok"] is True

    after = {card["label"]: card["value"] for card in client.get("/api/road/stats").json()["cards"]}
    assert after["重点观测道路"] == before["重点观测道路"] - 1

    observing = client.get("/api/road", params={"status": "重点观测"}).json()
    assert observing["total"] == 0
    closed = client.get("/api/road", params={"status": "封闭施工"}).json()
    assert [item["id"] for item in closed["items"]] == [3]


def test_repeated_action_does_not_double_apply_or_clobber_others():
    """同一件事重复提交只生效一次，其它设施的状态不被覆盖。"""
    assert _action(1, "办理移交").json()["ok"] is True
    again = _action(1, "办理移交").json()
    assert again["ok"] is False
    assert "正常养护" in again["message"]  # 已流转，当前状态这一头不允许
    assert _status(1) == "正常养护"
    assert _status(2) == "正常养护"
    assert _status(3) == "重点观测"


def test_duplicate_registration_does_not_create_second_record():
    """同一设施编码重复提交不能生成两条记录。"""
    payload = {"values": {"设施编码": "ROAD-0100", "道路名称": "测试路", "道路等级": "主干路"}}
    first = client.post("/api/road", json=payload).json()
    assert first["ok"] is True
    second = client.post("/api/road", json=payload).json()
    assert second["ok"] is False
    assert "ROAD-0100" in second["message"]

    listed = client.get("/api/road", params={"keyword": "ROAD-0100"}).json()
    assert listed["total"] == 1
    # 既有记录也不被重复提交覆盖
    assert listed["items"][0]["id"] == first["entry"]["id"]


def test_registration_keeps_original_flow():
    """原有登记流程照旧：缺字段要说明，登记成功从待移交起步。"""
    body = client.post("/api/road", json={"values": {"道路名称": "缺编码"}}).json()
    assert body["ok"] is False
    assert "设施编码" in body["message"]

    body = client.post(
        "/api/road", json={"values": {"设施编码": "ROAD-0200", "道路名称": "新登记路", "道路等级": "次干路"}}
    ).json()
    assert body["ok"] is True
    assert body["message"] == "道路设施已登记"
    assert body["entry"]["status"] == "待移交"
    assert body["entry"]["设施状态"] == "待移交"


def test_search_by_name_and_level_hits_expected_records():
    """按名称与等级找设施要能命中应有的记录。"""
    by_name = client.get("/api/road", params={"name": "道路设施样例3"}).json()
    assert [item["id"] for item in by_name["items"]] == [3]

    partial = client.get("/api/road", params={"name": "样例"}).json()
    assert partial["total"] == 3

    client.post("/api/road", json={"values": {"设施编码": "ROAD-0300", "道路名称": "滨江大道", "道路等级": "主干路"}})
    by_level = client.get("/api/road", params={"level": "主干路"}).json()
    assert [item["设施编码"] for item in by_level["items"]] == ["ROAD-0300"]

    combined = client.get("/api/road", params={"name": "滨江", "level": "主干路"}).json()
    assert combined["total"] == 1
    missed = client.get("/api/road", params={"name": "滨江", "level": "支路"}).json()
    assert missed["total"] == 0


def test_export_route_returns_list_not_error_page():
    """清单导出不再被 /{entry_id} 抢走，直接返回全量数据。"""
    response = client.get("/api/road/export")
    assert response.status_code == 200
    body = response.json()
    assert body["module"] == "road"
    assert body["total"] == len(body["items"]) == 3


def test_stats_route_not_shadowed_by_entry_id():
    response = client.get("/api/road/stats")
    assert response.status_code == 200
    labels = [card["label"] for card in response.json()["cards"]]
    assert labels == ["在养道路", "重点观测道路", "管养里程"]
