from dotenv import load_dotenv
load_dotenv()

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from pydantic import BaseModel

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from langfuse.langchain import CallbackHandler

from app.graphs.pipeline import build_graph, DEFAULT_RECURSION_LIMIT
from app.graphs.tracing import get_langfuse_client
from app.memory.store import memory_store

templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_uri = os.environ["DATABASE_URL"]
    async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpointer:
        await checkpointer.setup()
        app.state.checkpointer = checkpointer
        app.state.graph = build_graph(checkpointer=checkpointer)
        yield


app = FastAPI(lifespan=lifespan)


class ReviewDecision(BaseModel):
    approved: bool
    approved_intent: str | None = None
    feedback: str | None = None


def _build_callbacks(thread_id: str) -> list:
    """
    Langfuse's LangChain/LangGraph CallbackHandler automatically traces
    every node in the graph (including the conditional-edge routing
    functions) with zero manual per-node instrumentation -- a deliberate
    choice over the RAG project's manual span-per-call approach, since
    LangGraph is part of the LangChain ecosystem and has first-class
    support for this.

    THE REAL THING VERIFIED, NOT ASSUMED: a fresh CallbackHandler on each
    separate ainvoke() call (e.g. /process, then /review/{thread_id}
    resuming it) produces TWO DISCONNECTED traces by default -- confirmed
    experimentally with an injected in-memory exporter before writing this
    code. Seeding trace_context={"trace_id": ...} with the SAME
    deterministic ID (derived from thread_id via Langfuse's own documented
    create_trace_id(seed=...) helper) on every call for a given thread_id
    unifies them into ONE real trace spanning the human-approval pause --
    also confirmed experimentally, not assumed.
    """
    langfuse = get_langfuse_client()
    trace_id = langfuse.create_trace_id(seed=thread_id)
    return [CallbackHandler(trace_context={"trace_id": trace_id})]


def _format_result(state: dict, thread_id: str) -> dict:
    return {
        "status": "completed",
        "thread_id": thread_id,
        "classification": state["classification"],
        "result": state["agent_result"],
        "action": state["action_result"],
    }


def _format_pending(thread_id: str, state: dict) -> dict:
    interrupt_obj = state["__interrupt__"][0]
    return {"status": "pending_review", "thread_id": thread_id, "review": interrupt_obj.value}


def _log_completed(response: dict) -> None:
    memory_store["logs"].append({
        "classification": response["classification"],
        "result": response["result"],
        "action": response["action"],
    })


@app.get("/")
def root():
    return {"message": "Welcome to the Multi-Format AI System API"}


@app.post("/process")
async def process(file: UploadFile = File(...)):
    content = await file.read()
    thread_id = str(uuid.uuid4())
    config = {
        "configurable": {"thread_id": thread_id, "recursion_limit": DEFAULT_RECURSION_LIMIT},
        "callbacks": _build_callbacks(thread_id),
    }

    try:
        state = await app.state.graph.ainvoke(
            {"raw_content": content, "filename": file.filename}, config=config
        )
    except Exception as e:
        return {"status": "error", "error": f"Pipeline execution failed: {e}"}

    if "__interrupt__" in state:
        return _format_pending(thread_id, state)

    response = _format_result(state, thread_id)
    _log_completed(response)
    return response


@app.post("/review/{thread_id}")
async def submit_review(thread_id: str, decision: ReviewDecision):
    config = {
        "configurable": {"thread_id": thread_id, "recursion_limit": DEFAULT_RECURSION_LIMIT},
        "callbacks": _build_callbacks(thread_id),
    }

    snapshot = await app.state.graph.aget_state(config)
    if not snapshot.interrupts:
        raise HTTPException(
            status_code=400,
            detail=f"Thread {thread_id} has no pending review to submit (it doesn't exist, or already completed)",
        )

    resume_payload = decision.model_dump(exclude_none=True)
    try:
        state = await app.state.graph.ainvoke(Command(resume=resume_payload), config=config)
    except Exception as e:
        return {"status": "error", "error": f"Resume failed: {e}"}

    if "__interrupt__" in state:
        return _format_pending(thread_id, state)

    response = _format_result(state, thread_id)
    _log_completed(response)
    return response


@app.get("/review/{thread_id}")
async def get_review(thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await app.state.graph.aget_state(config)

    if not snapshot.interrupts:
        raise HTTPException(
            status_code=404,
            detail=f"No pending review for thread {thread_id} (either it doesn't exist, or it already completed)",
        )

    return {"status": "pending_review", "thread_id": thread_id, "review": snapshot.interrupts[0].value}


@app.get("/logs")
def get_logs():
    return memory_store["logs"]


@app.get("/ui", response_class=HTMLResponse)
def render_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})