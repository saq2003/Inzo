"""API integration tests: every endpoint group, offline via TestClient."""

from __future__ import annotations

import time


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "INZO"
    assert body["tools"] >= 5
    assert body["skills"] >= 4


def test_chat_calculate(client):
    resp = client.post("/api/chat", json={"message": "calculate (2+3)*4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "calculate"
    assert "20" in body["reply"]
    assert body["verified"] is True
    assert body["plan_steps"]


def test_chat_time(client):
    resp = client.post("/api/chat", json={"message": "what time is it?"})
    assert resp.status_code == 200
    assert resp.json()["intent"] == "get_time"


def test_chat_rejects_empty_message(client):
    resp = client.post("/api/chat", json={"message": ""})
    assert resp.status_code == 422


def test_tools_catalog(client):
    resp = client.get("/api/tools")
    names = [t["name"] for t in resp.json()]
    assert "calculator" in names
    assert "finance_calc" in names
    assert "shell" not in names


def test_tool_execute_ok(client):
    resp = client.post(
        "/api/tools/calculator/execute", json={"args": {"expression": "7*6"}}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "42" in body["output"]


def test_tool_execute_unknown_is_404(client):
    resp = client.post("/api/tools/nope/execute", json={"args": {}})
    assert resp.status_code == 404


def test_tool_execute_unpermissioned_actor_is_403(client):
    resp = client.post(
        "/api/tools/calculator/execute",
        json={"args": {"expression": "1+1"}, "actor": "intruder"},
    )
    assert resp.status_code == 403


def test_skills_list_and_toggle(client):
    names = [s["name"] for s in client.get("/api/skills").json()]
    assert "calculator" in names and "time" in names

    resp = client.post("/api/skills/time/disable")
    assert resp.json()["enabled"] is False
    resp = client.post("/api/skills/time/enable")
    assert resp.json()["enabled"] is True


def test_skill_unknown_is_404(client):
    assert client.post("/api/skills/nope/enable").status_code == 404


def test_memory_store_and_recall(client):
    stored = client.post(
        "/api/memory/store",
        json={"text": "INZO test fact: the sky reflector is teal", "kind": "fact"},
    ).json()
    assert stored["id"]

    recalled = client.post(
        "/api/memory/recall", json={"query": "sky reflector teal"}
    ).json()
    assert any("teal" in h["text"] for h in recalled["hits"])


def test_memory_stats(client):
    resp = client.get("/api/memory/stats")
    assert resp.status_code == 200
    assert "long_term_items" in resp.json()


def test_tasks_submit_list_get(client):
    submitted = client.post(
        "/api/tasks",
        json={"name": "index docs", "kind": "index_documents", "payload": {"paths": []}},
    )
    assert submitted.status_code == 200
    task_id = submitted.json()["id"]

    listed = client.get("/api/tasks").json()
    assert any(t["id"] == task_id for t in listed)

    # Allow the background task a moment, then inspect.
    time.sleep(0.3)
    fetched = client.get(f"/api/tasks/{task_id}").json()
    assert fetched["status"] in ("done", "running", "pending")


def test_task_unknown_is_404(client):
    assert client.get("/api/tasks/does-not-exist").status_code == 404


def test_voice_confident_transcript(client):
    resp = client.post(
        "/api/voice/process",
        json={"transcript": "calculate 3*3", "confidence": 0.9},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["needs_repetition"] is False
    assert "9" in body["reply"]


def test_voice_low_confidence_asks_repetition(client):
    resp = client.post(
        "/api/voice/process",
        json={"transcript": "mumble mumble", "confidence": 0.1},
    )
    assert resp.status_code == 200
    assert resp.json()["needs_repetition"] is True


def test_voice_missing_input_is_400(client):
    assert client.post("/api/voice/process", json={}).status_code == 400


def test_settings_view_and_update(client):
    view = client.get("/api/settings").json()
    assert view["app_name"] == "INZO"

    updated = client.put("/api/settings", json={"log_level": "warning"}).json()
    assert updated["log_level"] == "WARNING"
    # Restore for other tests.
    client.put("/api/settings", json={"log_level": "info"})
