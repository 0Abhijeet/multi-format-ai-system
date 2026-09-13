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

from app.graphs.pipeline import build_graph, DEFAULT_RECURSION_LIMIT
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


def _format_result(state: dict) -> dict:
    return {
        "status": "completed",
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
    config = {"configurable": {"thread_id": thread_id, "recursion_limit": DEFAULT_RECURSION_LIMIT}}

    try:
        state = await app.state.graph.ainvoke(
            {"raw_content": content, "filename": file.filename}, config=config
        )
    except Exception as e:
        return {"status": "error", "error": f"Pipeline execution failed: {e}"}

    if "__interrupt__" in state:
        return _format_pending(thread_id, state)

    response = _format_result(state)
    _log_completed(response)
    return response


@app.post("/review/{thread_id}")
async def submit_review(thread_id: str, decision: ReviewDecision):
    config = {"configurable": {"thread_id": thread_id, "recursion_limit": DEFAULT_RECURSION_LIMIT}}

    checkpoint_tuple = await app.state.checkpointer.aget_tuple(config)
    if checkpoint_tuple is None:
        raise HTTPException(status_code=404, detail=f"No such review thread: {thread_id}")

    resume_payload = decision.model_dump(exclude_none=True)
    try:
        state = await app.state.graph.ainvoke(Command(resume=resume_payload), config=config)
    except Exception as e:
        return {"status": "error", "error": f"Resume failed: {e}"}

    if "__interrupt__" in state:
        return _format_pending(thread_id, state)

    response = _format_result(state)
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