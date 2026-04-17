"""
tests/python/conftest.py — pytest shared fixtures

Provides:
  - client: FastAPI TestClient (no real Discord/Jira/LLM)
  - mock_groq_summarize / mock_groq_tasks: LLM patching fixtures

Notes:
  - discord is stubbed at sys.modules level (discord.py 2.x is incompatible
    with Python 3.13 due to removed audioop module)
  - GROQ_API_KEY is set to a dummy value so pipeline code doesn't KeyError
  - ChatGroq is patched at the langchain_groq source level because it is
    imported inside async functions, not at module top-level
"""

import os
import sys
import types
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ── Set dummy env vars before any pipeline import ─────────────────────────────

os.environ.setdefault("GROQ_API_KEY",        "test-groq-key-dummy")
os.environ.setdefault("DISCORD_TOKEN",       "test-discord-token")
os.environ.setdefault("DISCORD_GUILD_ID",    "123456789")
os.environ.setdefault("ANTHROPIC_API_KEY",   "test-anthropic-key")

# ── Stub out discord before any pipeline module imports it ────────────────────

def _build_discord_stub() -> types.ModuleType:
    discord = types.ModuleType("discord")
    discord.Guild       = object
    discord.TextChannel = object
    discord.Thread      = object
    discord.Forbidden   = Exception

    abc = types.ModuleType("discord.abc")
    abc.Messageable = object
    discord.abc = abc
    sys.modules["discord.abc"] = abc
    sys.modules["discord"]     = discord
    return discord

_build_discord_stub()

# ── Dummy LLM response helper ─────────────────────────────────────────────────

def make_llm_response(content: str) -> MagicMock:
    mock = MagicMock()
    mock.content = content
    return mock

# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest.fixture
def client():
    from pipeline.api import app
    from fastapi.testclient import TestClient
    return TestClient(app)

# ── LLM mock fixtures ─────────────────────────────────────────────────────────
#
# ChatGroq is constructed INSIDE async functions in pipeline code, so we patch
# langchain_groq.ChatGroq — the class itself — to return a mock instance.
# The mock instance's .ainvoke() is what tests control.

@pytest.fixture
def mock_groq_summarize():
    """Patch ChatGroq used anywhere (summarize, api) for summarization calls."""
    with patch("langchain_groq.ChatGroq") as MockClass:
        instance = MagicMock()
        instance.ainvoke = AsyncMock(
            return_value=make_llm_response('{"summary":"","decisions":[],"blockers":[]}')
        )
        MockClass.return_value = instance
        yield instance.ainvoke

@pytest.fixture
def mock_groq_tasks():
    """Patch ChatGroq for task extraction calls."""
    with patch("langchain_groq.ChatGroq") as MockClass:
        instance = MagicMock()
        instance.ainvoke = AsyncMock(return_value=make_llm_response("[]"))
        MockClass.return_value = instance
        yield instance.ainvoke
