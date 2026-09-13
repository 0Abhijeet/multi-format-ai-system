import os
from types import SimpleNamespace

import pytest
import pytest_asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

import app.graphs.critic_agent as critic_module
import app.graphs.tool_calling_agent as tool_module


def fake_message(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def fake_tool_call(name):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments="{}"))


class ScriptedGroqClient:
    """
    Lets a test force an exact sequence of critic/tool-calling LLM
    responses, shaped identically to Groq's real ChatCompletionMessage
    (content for JSON mode, tool_calls[i].function.name/.arguments for
    function-calling -- verified against groq's actual type definitions,
    not guessed). Used throughout this suite instead of real Groq calls:
    CI shouldn't burn real API quota on every push, and scripting is the
    only way to deterministically force specific branches (low confidence,
    which tool gets called) on demand.
    """
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    class _Completions:
        def __init__(self, outer):
            self.outer = outer

        async def create(self, **kwargs):
            self.outer.calls.append(kwargs)
            response = self.outer.script.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(message=response)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


@pytest.fixture
def patch_groq():
    """Tests call this with a list of fake_message(...)/fake_tool_call(...)
    responses; patches both critic_agent and tool_calling_agent's
    get_groq_client to the scripted fake and returns the client so tests
    can inspect .calls (e.g. to assert the critic was genuinely called
    twice in a reject-loop, not just once)."""
    def _patch(script):
        client = ScriptedGroqClient(script)
        critic_module.get_groq_client = lambda: client
        tool_module.get_groq_client = lambda: client
        return client
    return _patch


@pytest_asyncio.fixture
async def checkpointer():
    """Fresh AsyncPostgresSaver per test, against DATABASE_URL. setup() is
    idempotent (CREATE TABLE IF NOT EXISTS style) -- safe to call every
    test, not just once."""
    db_uri = os.environ["DATABASE_URL"]
    async with AsyncPostgresSaver.from_conn_string(db_uri) as cp:
        await cp.setup()
        yield cp