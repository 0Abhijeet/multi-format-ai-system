# Multi-Format AI System

A document-intake pipeline built as a real LangGraph state machine: upload an email, JSON payload, or PDF, and the system classifies it, extracts structured data via a format-specific agent, and decides what action to take — escalate to a CRM, fire a compliance/risk alert, or do nothing — using an LLM-driven critic and tool-calling agent, not hardcoded rules.

The original version was pure rule-based Python (regex classification, hardcoded if/elif dispatch, no LLM anywhere despite the `agents/` naming). This project rebuilt the orchestration layer from scratch to close a specific, confirmed skill gap: multi-agent coordination, tool-calling/function-calling agents, and human-in-the-loop workflows.

## What this demonstrates

- Ported an existing rule-based pipeline into a real LangGraph `StateGraph`, faithfully first (preserving known bugs deliberately) before evolving it — not a from-scratch rebuild
- Replaced hardcoded action-dispatch logic with a real tool-calling/function-calling agent that decides at runtime which tools to invoke, based on actual document content — caught a real compliance-alert case the original hardcoded logic structurally could never have caught (see `PROJECT_DETAILS.md` §3)
- Built a genuine second agent (a critic) whose confidence assessment drives real conditional routing — not a relabeled function — deliberately redesigned mid-build after the first version was assessed as too linear to honestly count as multi-agent coordination
- Implemented human-in-the-loop approval with a real reject-and-reconsider loop (not approve-only), backed by Postgres-based checkpointing verified to survive an actual process restart
- Investigated and documented a genuine, non-obvious LangGraph behavior: `recursion_limit` does not fire across interrupt/resume boundaries — verified experimentally at the tightest possible limit, rather than assumed
- Instrumented the entire graph with Langfuse tracing (LangChain/LangGraph-native `CallbackHandler`), including a real bug found and fixed before shipping: separate invocations produce disconnected traces by default, fixed via deterministic trace-ID seeding so a paused-and-resumed request appears as one unified trace
- Built a full pytest suite (18 tests) and GitHub Actions CI from scratch — this repo had neither before this work — covering every conditional branch including forced tool-calls, forced interrupts, and the recursion-limit boundary

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| Orchestration | LangGraph (`StateGraph`, async nodes, conditional edges, `interrupt()`) |
| Checkpointing | PostgreSQL via `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`) |
| LLM | Groq (critic agent + tool-calling agent) |
| Observability | Langfuse — LangChain/LangGraph-native `CallbackHandler`, deterministic trace-ID seeding for HITL flows |
| Testing | pytest, pytest-asyncio, run against a real Postgres instance |
| CI/CD | GitHub Actions (built from scratch for this project) |

## Architecture decisions (and why)

| Decision | Reasoning |
|---|---|
| Faithful 1:1 port before evolving the graph | Fixing known bugs (dead `"policy"` branch, intent-overwrite) during the port would have made it impossible to tell whether the port itself was correct versus whether behavior changed for unrelated reasons |
| Critic's confidence drives a real conditional branch, not a fixed hand-off | An earlier design where the critic always proceeded to the same next node was assessed as a two-step pipeline wearing a multi-agent costume — nothing about it required two agents to exist |
| Postgres-backed checkpointing, not `MemorySaver` | Required infrastructure for `interrupt()` to survive anything beyond the same process's memory — not optional polish, since human-in-the-loop is meaningless if a restart loses the paused state |
| Human reviewer gets a genuine reject path, not approve-only | Makes the interrupt an actual gate rather than a rubber stamp, and gives the recursion-limit requirement a real loop to investigate rather than a manufactured one |
| `langfuse.langchain.CallbackHandler` (automatic) over manual per-node spans | This app is built on LangGraph/LangChain, which has first-class Langfuse support — automatic tracing covers every node, including conditional-edge routing functions, with zero manual wrapping code |
| Deterministic Langfuse trace-ID seeding from `thread_id` | A fresh `CallbackHandler` on each separate `ainvoke()` call produces disconnected trace IDs by default — confirmed experimentally before shipping. Seeding both `/process` and `/review/{thread_id}`'s handler with the same `create_trace_id(seed=thread_id)` unifies a paused-and-resumed request into one real trace |
| Separate Postgres database, separate Langfuse project | Keeps this project's infrastructure independent from other projects sharing the same accounts — mirrors the same separation applied to AWS credentials elsewhere |

## Known limitations

Said out loud on purpose — demonstrating I understand the tradeoffs matters more than pretending they don't exist:

- `json_agent.py`'s Webhook-detection has a real, documented gap: a partial webhook payload missing its `id` field is invisible to validation, since intent-detection requires `event` AND `id` both present just to classify something as `"Webhook"` in the first place. Deliberately left unfixed — its output feeds directly into the critic agent, and changing it would require re-verifying everything already confirmed working
- Live low-confidence human-review trigger not yet observed in production at time of writing — the mechanism is fully verified (real interrupt, real resume, real reject-loop, real restart-survival), but every live document tried so far has resolved confidently on the real model's first pass
- No cost/token tracking in the Langfuse dashboard for this app — the generic LangChain/LangGraph callback integration doesn't parse Groq's token-usage metadata the way a native/manual wrapper would
- `route_action()` (the original hardcoded dispatch function) is dead code, kept intentionally as documented legacy reference — nothing in the live app calls it anymore
- Recursion limit does not meaningfully bound the human-review reject loop — that loop is bounded by the interrupt mechanism itself (a human has to keep actively rejecting), not by `recursion_limit`, which resets at every interrupt/resume boundary

## Local development

```bash
cp .env.example .env   # add GROQ_API_KEY, DATABASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
```

Create the checkpoint database:
```sql
CREATE DATABASE mf_agent_checkpoints;
```

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run tests:
```bash
pytest -v
```

Full build log, real bugs found and fixed, and design-decision reasoning: [`PROJECT_DETAILS.md`](.Project_docs/PROJECT_DETAILS.md)