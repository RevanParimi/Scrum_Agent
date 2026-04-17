"""
tests/python/test_api.py — FastAPI endpoint tests

DUMMY PIPELINE: LLM calls are mocked via conftest fixtures.
No real Groq/LLM API, no real Discord, no real Jira.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "service": "scrum-pipeline"}


# ── /pipeline/summarize ───────────────────────────────────────────────────────

class TestSummarizeEndpoint:
    DUMMY_RAW = {
        "standup": [
            "[2026-04-16 09:00] alice: working on auth",
            "[2026-04-16 09:01] bob: fixing CI pipeline",
        ],
        "blockers": ["[2026-04-16 09:05] bob: CI env var missing"],
    }

    DUMMY_LLM_RESPONSE = json.dumps({
        "summary": "Alice is working on auth. Bob is fixing CI.",
        "decisions": ["Use JWT for auth"],
        "blockers": ["CI env var missing"],
    })

    def test_summarize_returns_structured_response(self, client, mock_groq_summarize):
        mock_groq_summarize.return_value = MagicMock(content=self.DUMMY_LLM_RESPONSE)
        resp = client.post("/pipeline/summarize", json={"raw_messages": self.DUMMY_RAW})
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert isinstance(data["decisions"], list)
        assert isinstance(data["blockers"], list)

    def test_summarize_returns_correct_values(self, client, mock_groq_summarize):
        mock_groq_summarize.return_value = MagicMock(content=self.DUMMY_LLM_RESPONSE)
        resp = client.post("/pipeline/summarize", json={"raw_messages": self.DUMMY_RAW})
        data = resp.json()
        assert data["summary"] == "Alice is working on auth. Bob is fixing CI."
        assert "Use JWT for auth" in data["decisions"]
        assert "CI env var missing" in data["blockers"]

    def test_summarize_with_empty_messages(self, client, mock_groq_summarize):
        resp = client.post("/pipeline/summarize", json={"raw_messages": {}})
        assert resp.status_code == 200
        data = resp.json()
        # Empty messages → returns default no-activity response
        assert "summary" in data
        assert data["decisions"] == []
        assert data["blockers"] == []

    def test_summarize_handles_non_json_llm_response(self, client, mock_groq_summarize):
        # LLM returns plain text instead of JSON — should fall back gracefully
        mock_groq_summarize.return_value = MagicMock(content="Team had a good standup today.")
        resp = client.post("/pipeline/summarize", json={"raw_messages": self.DUMMY_RAW})
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Team had a good standup today."
        assert data["decisions"] == []
        assert data["blockers"] == []

    def test_summarize_rejects_missing_field(self, client):
        resp = client.post("/pipeline/summarize", json={})
        assert resp.status_code == 422   # Pydantic validation error


# ── /pipeline/extract-tasks ───────────────────────────────────────────────────

class TestExtractTasksEndpoint:
    PAYLOAD = {
        "summary": "Alice will implement JWT. Bob will fix CI.",
        "raw_messages": {
            "standup": [
                "[09:00] alice: I'll implement JWT auth middleware today",
                "[09:01] bob: I'll fix the CI env variable issue",
            ]
        },
    }

    DUMMY_TASKS = json.dumps([
        {"title": "Implement JWT auth middleware", "owner": "alice"},
        {"title": "Fix CI env variable",           "owner": "bob"},
    ])

    def test_returns_task_list(self, client, mock_groq_tasks):
        mock_groq_tasks.return_value = MagicMock(content=self.DUMMY_TASKS)
        resp = client.post("/pipeline/extract-tasks", json=self.PAYLOAD)
        assert resp.status_code == 200
        data = resp.json()
        assert "tasks" in data
        assert len(data["tasks"]) == 2

    def test_task_has_title_and_owner(self, client, mock_groq_tasks):
        mock_groq_tasks.return_value = MagicMock(content=self.DUMMY_TASKS)
        resp = client.post("/pipeline/extract-tasks", json=self.PAYLOAD)
        task = resp.json()["tasks"][0]
        assert "title" in task
        assert "owner" in task

    def test_returns_empty_list_when_llm_returns_empty(self, client, mock_groq_tasks):
        mock_groq_tasks.return_value = MagicMock(content="[]")
        resp = client.post("/pipeline/extract-tasks", json=self.PAYLOAD)
        assert resp.status_code == 200
        assert resp.json()["tasks"] == []

    def test_rejects_missing_summary(self, client):
        resp = client.post("/pipeline/extract-tasks", json={"raw_messages": {}})
        assert resp.status_code == 422


# ── /pipeline/run (full pipeline) ────────────────────────────────────────────

class TestFullPipelineEndpoint:
    PAYLOAD = {
        "raw_messages": {
            "standup": ["[09:00] alice: shipping login feature today"],
        },
        "report_date": "2026-04-16",
    }

    SUMMARY_RESPONSE = json.dumps({
        "summary": "Alice is shipping the login feature.",
        "decisions": [],
        "blockers": [],
    })
    TASKS_RESPONSE = json.dumps([
        {"title": "Ship login feature", "owner": "alice"}
    ])

    def test_full_pipeline_returns_all_fields(self, client, mock_groq_summarize, mock_groq_tasks):
        mock_groq_summarize.return_value = MagicMock(content=self.SUMMARY_RESPONSE)
        mock_groq_tasks.return_value    = MagicMock(content=self.TASKS_RESPONSE)

        with patch("pipeline.report_writer.append_to_team_log"), \
             patch("pipeline.report_writer.git_commit_and_push", return_value=True), \
             patch("pipeline.task_manager.load_sprint_state", return_value={"tasks": []}):

            resp = client.post("/pipeline/run", json=self.PAYLOAD)

        assert resp.status_code == 200
        data = resp.json()
        assert "summary"   in data
        assert "decisions" in data
        assert "blockers"  in data
        assert "new_tasks" in data
        assert "report_md" in data

    def test_full_pipeline_task_count(self, client, mock_groq_summarize, mock_groq_tasks):
        mock_groq_summarize.return_value = MagicMock(content=self.SUMMARY_RESPONSE)
        mock_groq_tasks.return_value    = MagicMock(content=self.TASKS_RESPONSE)

        with patch("pipeline.report_writer.append_to_team_log"), \
             patch("pipeline.report_writer.git_commit_and_push", return_value=True), \
             patch("pipeline.task_manager.load_sprint_state", return_value={"tasks": []}):

            resp = client.post("/pipeline/run", json=self.PAYLOAD)

        assert len(resp.json()["new_tasks"]) == 1
        assert resp.json()["new_tasks"][0]["title"] == "Ship login feature"
