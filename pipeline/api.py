"""
pipeline/api.py — FastAPI HTTP bridge

Exposes the Python AI pipeline as REST endpoints so the TypeScript
Mastra layer can call ingest, summarize, task-extraction, and report
without knowing anything about LangGraph internals.

Endpoints:
  POST /pipeline/run        — full daily pipeline (ingest → summarize → tasks → report)
  POST /pipeline/summarize  — summarize raw messages (no Discord I/O)
  POST /pipeline/extract-tasks — extract action items from a summary
  GET  /health              — liveness check
"""

import asyncio
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("pipeline-api")

app = FastAPI(title="Scrum Agent Pipeline API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ─────────────────────────────────────────────────

class RawMessagesPayload(BaseModel):
    """Channel-keyed message dict: { "standup": ["[ts] user: msg", ...] }"""
    raw_messages: dict[str, list[str]]


class SummarizeResponse(BaseModel):
    summary: str
    decisions: list[str]
    blockers: list[str]


class ExtractTasksPayload(BaseModel):
    summary: str
    raw_messages: dict[str, list[str]]


class TaskItem(BaseModel):
    title: str
    owner: str


class ExtractTasksResponse(BaseModel):
    tasks: list[TaskItem]


class FullPipelinePayload(BaseModel):
    """Payload when TypeScript has already ingested messages itself."""
    raw_messages: dict[str, list[str]]
    report_date: Optional[str] = None


class FullPipelineResponse(BaseModel):
    summary: str
    decisions: list[str]
    blockers: list[str]
    new_tasks: list[TaskItem]
    report_md: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "scrum-pipeline"}


@app.post("/pipeline/summarize", response_model=SummarizeResponse)
async def summarize_endpoint(payload: RawMessagesPayload):
    """
    Summarize raw Discord messages.
    Called by Mastra workflow step 2 (after ingest in TypeScript).
    """
    from pipeline.summarize import summarize_node
    from pipeline.schema import empty_state

    state = empty_state()
    state["raw_messages"] = payload.raw_messages

    try:
        result = await summarize_node(state)
        return SummarizeResponse(
            summary=result["summary"],
            decisions=result["decisions"],
            blockers=result["blockers"],
        )
    except Exception as exc:
        logger.exception("Summarize failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/pipeline/extract-tasks", response_model=ExtractTasksResponse)
async def extract_tasks_endpoint(payload: ExtractTasksPayload):
    """
    Extract action items from a summary + raw messages.
    Called by Mastra workflow step 3 (task manager).
    """
    from pipeline.task_manager import extract_action_items

    try:
        items = await extract_action_items(payload.summary, payload.raw_messages)
        return ExtractTasksResponse(tasks=[TaskItem(**i) for i in items])
    except Exception as exc:
        logger.exception("Extract tasks failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/pipeline/run", response_model=FullPipelineResponse)
async def run_pipeline_endpoint(payload: FullPipelinePayload):
    """
    Run the full AI pipeline given pre-ingested messages.
    TypeScript ingest (discord.js) → POST here → get summary + tasks + report_md.
    """
    from pipeline.summarize import summarize_node
    from pipeline.task_manager import extract_action_items, load_sprint_state
    from pipeline.report_writer import build_report_markdown, append_to_team_log, git_commit_and_push
    from pipeline.schema import empty_state
    from datetime import date

    report_date = payload.report_date or str(date.today())
    state = empty_state()
    state["raw_messages"] = payload.raw_messages
    state["report_date"] = report_date

    try:
        # Step 1: Summarize
        state = await summarize_node(state)

        # Step 2: Extract tasks (standup + blockers only, not sprint-discuss)
        standup_msgs = {
            src: msgs
            for src, msgs in payload.raw_messages.items()
            if not src.startswith("sprint-discuss")
        }
        raw_items = await extract_action_items(state["summary"], standup_msgs)
        new_tasks = [TaskItem(title=i["title"], owner=i.get("owner", "unassigned")) for i in raw_items]

        # Step 3: Build report markdown
        state["new_tasks"] = [
            {"id": f"T{idx+1}", "title": t.title, "owner": t.owner,
             "status": "open", "thread_id": None, "created_date": report_date}
            for idx, t in enumerate(new_tasks)
        ]
        state["tasks"] = load_sprint_state().get("tasks", []) + state["new_tasks"]
        report_md = build_report_markdown(state)

        # Step 4: Write team log + git push
        append_to_team_log(report_md)
        git_commit_and_push(report_date)

        return FullPipelineResponse(
            summary=state["summary"],
            decisions=state["decisions"],
            blockers=state["blockers"],
            new_tasks=new_tasks,
            report_md=report_md,
        )

    except Exception as exc:
        logger.exception("Full pipeline failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("pipeline.api:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
