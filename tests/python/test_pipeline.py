"""
tests/python/test_pipeline.py — Pipeline module unit tests

Tests for:
  - pipeline/summarize.py  — parse_structured_response, build_context_block
  - pipeline/task_manager.py — next_task_id, extract_action_items
  - pipeline/report_writer.py — build_report_markdown, chunk_message
  - pipeline/schema.py — empty_state

No real LLM, Discord, or file I/O needed for most tests.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── pipeline/schema.py ────────────────────────────────────────────────────────

class TestSchema:
    def test_empty_state_has_required_keys(self):
        from pipeline.schema import empty_state
        state = empty_state()
        required = ["raw_messages", "fetch_since_hours", "summary", "decisions",
                    "blockers", "user_stories", "tasks", "new_tasks", "report_md", "report_date"]
        for key in required:
            assert key in state, f"Missing key: {key}"

    def test_empty_state_default_fetch_hours(self):
        from pipeline.schema import empty_state
        assert empty_state()["fetch_since_hours"] == 24

    def test_empty_state_custom_fetch_hours(self):
        from pipeline.schema import empty_state
        assert empty_state(fetch_since_hours=168)["fetch_since_hours"] == 168

    def test_empty_state_report_date_is_today(self):
        from pipeline.schema import empty_state
        from datetime import date
        assert empty_state()["report_date"] == str(date.today())


# ── pipeline/summarize.py ─────────────────────────────────────────────────────

class TestSummarize:
    def test_parse_valid_json_response(self):
        from pipeline.summarize import parse_structured_response
        raw = json.dumps({
            "summary": "Team shipped login feature.",
            "decisions": ["Use JWT"],
            "blockers": ["CI is down"],
        })
        summary, decisions, blockers = parse_structured_response(raw)
        assert summary == "Team shipped login feature."
        assert decisions == ["Use JWT"]
        assert blockers == ["CI is down"]

    def test_parse_json_embedded_in_prose(self):
        from pipeline.summarize import parse_structured_response
        raw = 'Here is the summary:\n{"summary": "All good.", "decisions": [], "blockers": []}'
        summary, decisions, blockers = parse_structured_response(raw)
        assert summary == "All good."
        assert decisions == []

    def test_parse_fallback_on_plain_text(self):
        from pipeline.summarize import parse_structured_response
        raw = "Team had a productive standup."
        summary, decisions, blockers = parse_structured_response(raw)
        assert summary == raw.strip()
        assert decisions == []
        assert blockers == []

    def test_parse_fallback_on_malformed_json(self):
        from pipeline.summarize import parse_structured_response
        raw = '{"summary": "broken json", decisions: []}'
        summary, decisions, blockers = parse_structured_response(raw)
        assert summary == raw.strip()

    def test_build_context_block_formats_messages(self):
        from pipeline.summarize import build_context_block
        raw = {
            "standup": ["[09:00] alice: working on login"],
            "blockers": ["[09:05] bob: CI broken"],
        }
        block = build_context_block(raw)
        assert "### standup" in block
        assert "alice: working on login" in block
        assert "### blockers" in block

    def test_build_context_block_truncates_large_input(self):
        from pipeline.summarize import build_context_block, MAX_CONTEXT_CHARS
        # Create a payload larger than the limit
        big_messages = ["x" * 1000] * 200
        raw = {f"channel-{i}": big_messages for i in range(100)}
        block = build_context_block(raw)
        assert len(block) <= MAX_CONTEXT_CHARS + 1000   # allow one block overshoot


# ── pipeline/task_manager.py ──────────────────────────────────────────────────

class TestTaskManager:
    def test_next_task_id_empty(self):
        from pipeline.task_manager import next_task_id
        assert next_task_id([]) == "T1"

    def test_next_task_id_increments(self):
        from pipeline.task_manager import next_task_id
        tasks = [{"id": "T3"}, {"id": "T7"}]
        assert next_task_id(tasks) == "T8"

    def test_next_task_id_handles_non_numeric(self):
        from pipeline.task_manager import next_task_id
        tasks = [{"id": "T1"}, {"id": "bad-id"}]
        assert next_task_id(tasks) == "T2"

    @pytest.mark.asyncio
    async def test_extract_action_items_returns_list(self, mock_groq_tasks):
        from pipeline.task_manager import extract_action_items
        dummy_tasks = [
            {"title": "Fix CI pipeline", "owner": "bob"},
            {"title": "Implement auth",  "owner": "alice"},
        ]
        mock_groq_tasks.return_value = MagicMock(content=json.dumps(dummy_tasks))
        result = await extract_action_items("Some summary", {"standup": ["alice: working on auth"]})
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["title"] == "Fix CI pipeline"

    @pytest.mark.asyncio
    async def test_extract_action_items_returns_empty_on_llm_failure(self, mock_groq_tasks):
        from pipeline.task_manager import extract_action_items
        mock_groq_tasks.return_value = MagicMock(content="not valid json at all")
        result = await extract_action_items("Summary", {})
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_action_items_returns_empty_on_empty_array(self, mock_groq_tasks):
        from pipeline.task_manager import extract_action_items
        mock_groq_tasks.return_value = MagicMock(content="[]")
        result = await extract_action_items("Nothing to do", {})
        assert result == []


# ── pipeline/report_writer.py ─────────────────────────────────────────────────

class TestReportWriter:
    BASE_STATE = {
        "report_date": "2026-04-16",
        "summary": "Team shipped login feature and fixed CI.",
        "decisions": ["Use JWT for auth", "Deploy every Friday"],
        "blockers": ["Staging env is down"],
        "new_tasks": [
            {"id": "T1", "title": "Fix staging env", "owner": "bob", "status": "open"}
        ],
        "tasks": [
            {"id": "T1", "title": "Fix staging env",   "owner": "bob",   "status": "open"},
            {"id": "T2", "title": "Implement JWT auth", "owner": "alice", "status": "in_progress"},
        ],
    }

    def test_report_contains_date(self):
        from pipeline.report_writer import build_report_markdown
        md = build_report_markdown(self.BASE_STATE)
        assert "2026-04-16" in md

    def test_report_contains_summary(self):
        from pipeline.report_writer import build_report_markdown
        md = build_report_markdown(self.BASE_STATE)
        assert "Team shipped login feature" in md

    def test_report_contains_decisions(self):
        from pipeline.report_writer import build_report_markdown
        md = build_report_markdown(self.BASE_STATE)
        assert "Use JWT for auth" in md
        assert "Deploy every Friday" in md

    def test_report_contains_blockers(self):
        from pipeline.report_writer import build_report_markdown
        md = build_report_markdown(self.BASE_STATE)
        assert "Staging env is down" in md

    def test_report_contains_new_tasks_table(self):
        from pipeline.report_writer import build_report_markdown
        md = build_report_markdown(self.BASE_STATE)
        assert "New Tasks Created" in md
        assert "Fix staging env" in md

    def test_report_contains_open_task_board(self):
        from pipeline.report_writer import build_report_markdown
        md = build_report_markdown(self.BASE_STATE)
        assert "Open Task Board" in md
        assert "Implement JWT auth" in md

    def test_report_skips_decisions_section_when_empty(self):
        from pipeline.report_writer import build_report_markdown
        state = {**self.BASE_STATE, "decisions": []}
        md = build_report_markdown(state)
        assert "### Decisions" not in md

    def test_report_skips_blockers_section_when_empty(self):
        from pipeline.report_writer import build_report_markdown
        state = {**self.BASE_STATE, "blockers": []}
        md = build_report_markdown(state)
        assert "### Blockers" not in md

    def test_chunk_message_short_text(self):
        from pipeline.report_writer import chunk_message
        chunks = chunk_message("Hello world")
        assert chunks == ["Hello world"]

    def test_chunk_message_splits_at_newline(self):
        from pipeline.report_writer import chunk_message
        # Create text just over the limit that has a newline to split at
        line_a = "A" * 1000
        line_b = "B" * 1000
        text = line_a + "\n" + line_b
        chunks = chunk_message(text, limit=1500)
        assert len(chunks) == 2
        assert chunks[0] == line_a
        assert chunks[1] == line_b

    def test_chunk_message_hard_splits_when_no_newline(self):
        from pipeline.report_writer import chunk_message
        text = "X" * 5000
        chunks = chunk_message(text, limit=2000)
        assert len(chunks) == 3   # 2000 + 2000 + 1000
        assert all(len(c) <= 2000 for c in chunks)
