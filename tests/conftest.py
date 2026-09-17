import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

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
    def _patch(script):
        client = ScriptedGroqClient(script)
        critic_module.get_groq_client = lambda: client
        tool_module.get_groq_client = lambda: client
        return client
    return _patch


@pytest_asyncio.fixture
async def checkpointer():
    db_uri = os.environ["DATABASE_URL"]
    async with AsyncPostgresSaver.from_conn_string(db_uri) as cp:
        await cp.setup()
        yield cp