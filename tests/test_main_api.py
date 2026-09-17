"""
Full HTTP-level tests against the real FastAPI app: real lifespan (real
AsyncPostgresSaver connection, same as a real server startup), real
ASGITransport requests. Groq scripted via patch_groq -- everything else
real and unmocked.

NOTE: httpx.ASGITransport does NOT run FastAPI's lifespan events
automatically (checked its constructor signature directly before assuming
this -- not discovered via a failure). Tests must manually enter
app.router.lifespan_context(app) or app.state.graph/checkpointer will
never be set.
"""
import json as json_lib

import httpx
import pytest
import pytest_asyncio

from app.main import app
from tests.conftest import fake_message, fake_tool_call


@pytest_asyncio.fixture
async def client(patch_groq):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.mark.asyncio
async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_process_completes_high_confidence(client, patch_groq):
    patch_groq([
        fake_message(content=json_lib.dumps({"trusted_intent": "RFQ", "confidence": "high", "note": "clear"})),
        fake_message(tool_calls=None),
    ])
    r = await client.post("/process", files={"file": ("q.eml", b"From: a@b.com\nquote please", "message/rfc822")})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["action"] == "no_action"


@pytest.mark.asyncio
async def test_process_pending_review_then_approve_via_endpoint(client, patch_groq):
    patch_groq([fake_message(content=json_lib.dumps({"trusted_intent": "Webhook", "confidence": "low", "note": "ambiguous"}))])
    r = await client.post("/process", files={"file": ("w.json", b'{"id":"e1","event":"flagged_fraud"}', "application/json")})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_review"
    thread_id = body["thread_id"]
    assert body["review"]["reason"]

    r = await client.get(f"/review/{thread_id}")
    assert r.status_code == 200
    assert r.json()["thread_id"] == thread_id

    patch_groq([fake_message(tool_calls=[fake_tool_call("post_to_crm")])])
    r = await client.post(f"/review/{thread_id}", json={"approved": True, "approved_intent": "Fraud Risk"})
    assert r.status_code == 200
    body2 = r.json()
    assert body2["status"] == "completed"
    assert body2["action"] == "post_to_crm"

    r = await client.get("/logs")
    logs = r.json()
    assert any(log["action"] == "post_to_crm" for log in logs)


@pytest.mark.asyncio
async def test_get_review_unknown_thread_404s(client):
    r = await client.get("/review/does-not-exist")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_review_unknown_thread_400s(client):
    r = await client.post("/review/totally-fake-id", json={"approved": True})
    assert r.status_code == 400