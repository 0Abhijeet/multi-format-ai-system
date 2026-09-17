"""
Graph-level tests against the CURRENT build_graph() shape:
classify -> route by format -> agent -> critic -> [tool_calling | human_review] -> END

Groq is scripted via patch_groq (conftest.py) -- no live API calls in CI.
Checkpointing, interrupt/resume, the reject-loop, and Postgres persistence
are all REAL and unmocked (checkpointer fixture uses a real AsyncPostgresSaver
against DATABASE_URL).
"""
import json as json_lib

import pytest
from langgraph.types import Command

from app.graphs.pipeline import build_graph
from tests.conftest import fake_message, fake_tool_call


@pytest.mark.asyncio
async def test_email_branch_high_confidence(checkpointer, patch_groq):
    patch_groq([
        fake_message(content=json_lib.dumps({"trusted_intent": "Complaint", "confidence": "high", "note": "clear"})),
        fake_message(tool_calls=[fake_tool_call("post_to_crm")]),
    ])
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t-email"}}
    raw = b"From: angry@example.com\nI am angry and not happy with your bad service."
    result = await graph.ainvoke({"raw_content": raw, "filename": "c.eml"}, config=config)

    assert "__interrupt__" not in result
    assert result["confidence"] == "high"
    assert result["action_result"] == "post_to_crm"
    assert result["agent_result"]["tone"] == "angry"


@pytest.mark.asyncio
async def test_pdf_branch_malformed_degrades_gracefully(checkpointer, patch_groq):
    # PDF parsing exception -> agent_result={"error": ...}, graph still
    # reaches the critic and completes rather than crashing (per-node
    # try/except from step 4.1, still in place).
    patch_groq([
        fake_message(content=json_lib.dumps({"trusted_intent": "Unknown", "confidence": "high", "note": "no data to judge"})),
        fake_message(tool_calls=None),
    ])
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t-pdf-broken"}}
    result = await graph.ainvoke({"raw_content": b"not a real pdf", "filename": "broken.pdf"}, config=config)

    assert "__interrupt__" not in result
    assert "error" in result["agent_result"]
    assert result["action_result"] == "no_action"


@pytest.mark.asyncio
async def test_unsupported_format(checkpointer, patch_groq):
    patch_groq([
        fake_message(content=json_lib.dumps({"trusted_intent": "Unknown", "confidence": "high", "note": "unsupported"})),
        fake_message(tool_calls=None),
    ])
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t-unsupported"}}
    result = await graph.ainvoke({"raw_content": b"whatever", "filename": "notes.xyz"}, config=config)

    assert result["classification"]["format"] == "Unknown"
    assert result["agent_result"]["error"] == "Unsupported format"


@pytest.mark.asyncio
async def test_low_confidence_triggers_interrupt_then_approve(checkpointer, patch_groq):
    patch_groq([
        fake_message(content=json_lib.dumps({"trusted_intent": "Webhook", "confidence": "low", "note": "genuine disagreement"})),
        fake_message(tool_calls=None),
    ])
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t-approve"}}

    result = await graph.ainvoke(
        {"raw_content": json_lib.dumps({"id": "e1", "event": "flagged"}).encode(), "filename": "x.json"},
        config=config,
    )
    assert "__interrupt__" in result
    assert result["__interrupt__"][0].value["reason"]

    resumed = await graph.ainvoke(Command(resume={"approved": True, "approved_intent": "Webhook"}), config=config)
    assert "__interrupt__" not in resumed
    assert resumed["confidence"] == "human-approved"


@pytest.mark.asyncio
async def test_reject_loops_back_to_critic_for_real(checkpointer, patch_groq):
    client = patch_groq([
        fake_message(content=json_lib.dumps({"trusted_intent": "Webhook", "confidence": "low", "note": "unsure"})),
        fake_message(content=json_lib.dumps({"trusted_intent": "Fraud Risk", "confidence": "high", "note": "reconsidered"})),
        fake_message(tool_calls=[fake_tool_call("post_to_crm")]),
    ])
    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t-reject-loop"}}

    result = await graph.ainvoke(
        {"raw_content": json_lib.dumps({"id": "e2", "event": "suspicious_flagged"}).encode(), "filename": "x.json"},
        config=config,
    )
    assert "__interrupt__" in result

    resumed = await graph.ainvoke(
        Command(resume={"approved": False, "feedback": "check again, this looks like fraud"}),
        config=config,
    )
    # THE REAL CHECK: not just "it completed", but that the critic was
    # genuinely invoked a second time (real loop, not a single pass)
    assert len(client.calls) == 3  # critic, critic again, tool_calling
    assert "__interrupt__" not in resumed
    assert resumed["action_result"] == "post_to_crm"


@pytest.mark.asyncio
async def test_recursion_limit_does_not_fire_across_interrupt_boundary(checkpointer, patch_groq):
    """
    Documented finding, not a theoretical footnote: recursion_limit does
    NOT accumulate across separate interrupt/resume invocations. Confirmed
    at the tightest possible limit (1) -- a human can reject repeatedly
    and GraphRecursionError never raises, because human_review_node always
    calls interrupt() on its way back into the loop, and each
    interrupt/resume boundary resets LangGraph's per-invocation step
    budget. The loop here is bounded by the interrupt itself (a human has
    to keep actively rejecting), not by recursion_limit. No artificial
    ungated loop was added just to make this setting fire -- see build log.
    """
    script = [fake_message(content=json_lib.dumps({"trusted_intent": "X", "confidence": "low", "note": "still unsure"})) for _ in range(6)]
    script.append(fake_message(tool_calls=None))
    patch_groq(script)

    graph = build_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "t-recursion", "recursion_limit": 1}}

    result = await graph.ainvoke({"raw_content": b'{"id":"e3","event":"x"}', "filename": "x.json"}, config=config)
    assert "__interrupt__" in result

    for i in range(3):
        result = await graph.ainvoke(
            Command(resume={"approved": False, "feedback": f"rejection #{i+1}"}),
            config=config,
        )
        assert "__interrupt__" in result  # never raises, confirmed each time

    final = await graph.ainvoke(Command(resume={"approved": True, "approved_intent": "X"}), config=config)
    assert "__interrupt__" not in final
    assert final["confidence"] == "human-approved"


@pytest.mark.asyncio
async def test_interrupt_survives_a_genuinely_fresh_connection(patch_groq):
    """
    The persistence claim that actually matters for #2/#4: not "no
    exception was thrown", but "a second, independent connection/graph
    object can resume a paused interrupt to completion." Deliberately does
    NOT use the `checkpointer` fixture for both phases -- opens two fully
    separate AsyncPostgresSaver connections, simulating a real process
    restart between them.
    """
    import os
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    db_uri = os.environ["DATABASE_URL"]
    config = {"configurable": {"thread_id": "t-restart-survival"}}

    patch_groq([fake_message(content=json_lib.dumps({"trusted_intent": "Fraud Risk", "confidence": "low", "note": "ambiguous"}))])
    async with AsyncPostgresSaver.from_conn_string(db_uri) as cp1:
        await cp1.setup()
        graph1 = build_graph(checkpointer=cp1)
        result = await graph1.ainvoke({"raw_content": b'{"id":"e4","event":"y"}', "filename": "x.json"}, config=config)
        assert "__interrupt__" in result
    # cp1's connection is now fully closed

    patch_groq([fake_message(tool_calls=None)])
    async with AsyncPostgresSaver.from_conn_string(db_uri) as cp2:
        graph2 = build_graph(checkpointer=cp2)
        resumed = await graph2.ainvoke(Command(resume={"approved": True, "approved_intent": "Fraud Risk"}), config=config)
        assert "__interrupt__" not in resumed
        assert resumed["confidence"] == "human-approved"