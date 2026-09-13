# Multi-Format AI System — Project Details

Full build log: real decisions, real bugs found and fixed, real verification —
written as the work happened, not reconstructed from memory afterward.

## What this project is

A document-intake pipeline: upload an email, JSON payload, or PDF, and the
system classifies it, extracts structured data via a format-specific agent,
and decides what action (if any) to take — escalate to a CRM, fire a
compliance/risk alert, or do nothing.

The original version (pre-this-work) was pure rule-based Python: regex
classification, hardcoded if/elif dispatch, no LLM anywhere in the code
despite the `agents/` folder naming. This work rebuilt the orchestration
layer as a real LangGraph state machine — closing a specific, confirmed
skill gap (multi-agent coordination, tool-calling/function-calling agents,
human-in-the-loop workflows), not just relabeling the existing logic.

## Architecture

```
classify_input
      |
[route by format]
      |
  +---+---+---+-----------+
  |       |   |           |
email   json pdf   unsupported
  |       |   |           |
  +---+---+---+-----------+
      |
    critic (LLM, real second agent)
      |
[route by confidence]
      |
  +---+---------------+
  |                    |
high conf         low conf
  |                    |
tool_calling <--- human_review
  |                (reject loops back to critic)
 END
```

Checkpointed via Postgres (`AsyncPostgresSaver`) — the graph can pause at
`human_review`'s `interrupt()` and resume later, including after a real
process restart.

---

## Bug Log — quick reference

Every real bug/finding below is documented in full in its section; this
table is a fast-scan index for interview revision, not new content.

| # | Where | What | Found by | Fix / resolution |
|---|---|---|---|---|
| 1 | §1 Linear port | Agent-node exceptions would propagate uncaught instead of degrading gracefully like the original | Self-caught before calling the step done | Added per-node try/except; verified with a real forced `PyPDF2` exception |
| 2 | §1 Linear port | First intent-overwrite test silently passed for the wrong reason — `"invoice_id"` key collided with `classify()`'s own regex | Inspecting actual test output before trusting the assertion | Rebuilt test with a field name that doesn't collide |
| 3 | §3 Critic/HITL | `recursion_limit` never fires across interrupt/resume boundaries, even at the tightest possible limit | Direct experimental isolation (limit=1, repeated rejects) | Documented as real behavior; no artificial loop added just to force it to fire |
| 4 | §3 Critic/HITL | Old hardcoded `route_action` could never fire a compliance alert unless intent was exactly `"regulation"`/`"policy"` | Live test with a real `"Complaint"`-labeled document containing GDPR/fraud language | New tool-calling node reads actual content, not just the intent label — confirmed live |
| 5 | §4 API wiring | `httpx.ASGITransport` doesn't run FastAPI lifespan events automatically | Checked the constructor signature before assuming | Tests manually enter `app.router.lifespan_context(app)` |
| 6 | §4 API wiring | `main.py` never called `load_dotenv()` — `.env` values present but never loaded | First real `uvicorn` startup attempt (`KeyError: DATABASE_URL`) | Added `load_dotenv()` at the top of `main.py` |
| 7 | §4 API wiring | `submit_review` accepted a resume on an already-completed thread, silently returning `200` | Live testing (an accidental Swagger placeholder-value request) | Switched to `graph.aget_state(config)` + `.interrupts` check; reproduced deliberately with a real completed thread, confirmed correct `400` |
| 8 | §4 API wiring | `thread_id` missing from `completed` responses (only present on `pending_review`) | Manual review while wiring Langfuse (needed it as the trace-ID seed) | Added to every response shape |
| 9 | §5 Tests/CI | `test_router.py` broken by the async conversion (`route_action` became `async def`, tests never awaited it) | First real `pytest` run | Converted to `@pytest.mark.asyncio` + `await` |
| 10 | §5 Tests/CI | `test_router.py`'s risk-alert test asserted an outcome its own input could never produce | Fixing bug #9 surfaced it | Corrected input to a real trigger case; added missing regulation-branch coverage |
| 11 | §5 Tests/CI | `json_agent.py` can't flag a partial Webhook payload as anomalous — intent-detection requires `event`+`id` both present just to classify it as Webhook at all | Running the pre-existing `test_agents.py` suite for the first time in this work | **Not fixed** — documented as a known gap; feeds directly into the critic, so changing it risks invalidating already-verified work |
| 12 | §6 Langfuse | A fresh `CallbackHandler` per `ainvoke()` call produces disconnected trace IDs by default | Experimentally, with an injected in-memory exporter, before writing production code | Seeded `create_trace_id(seed=thread_id)` identically on every call for a given thread — confirmed one unified trace, in sandbox and live |

---

## Section 1 — Linear graph port (baseline)

### Decision
Ported the existing classify → route → agent → dispatch flow into a
`StateGraph` as a **faithful 1:1 translation first**, deliberately
preserving two known bugs in the original logic rather than fixing them
during the port:
- a dead `"policy"` branch in `route_action` (`classify()` never produces
  that value, only `"Regulation"`)
- the classifier's regex-guessed intent unconditionally overwriting a
  format agent's own content-derived intent

Both were already scoped for later steps (tool-calling replaces
`route_action` entirely; the critic agent is the natural place to catch
the intent conflict). Fixing them during the port would have made it
impossible to tell whether the port itself was correct versus whether
behavior changed for unrelated reasons.

### Required fix (not optional, not a behavior change)
`retry_utils.retry_action` used blocking `time.sleep()`, which would
freeze the event loop inside an async graph node — the same class of bug
already fixed once in the RAG project's async rework. Converted to
`asyncio.sleep()`.

### Bugs found and fixed
1. **Self-caught gap in the port itself:** first version of the graph
   omitted the try/except the original `main.py` wraps around all three
   `process_*()` calls — an agent exception would have propagated
   uncaught through `ainvoke()` instead of degrading gracefully to
   `agent_result={"error": ...}` and continuing, as the original always
   does. Caught before calling this step done, fixed by adding
   per-node try/except to each agent node, verified with a real forced
   exception (malformed PDF bytes causing a genuine `PyPDF2`
   `"EOF marker not found"` error).
2. **Test-design bug, not a code bug:** the first intent-overwrite
   verification test used a JSON payload with the key `"invoice_id"` —
   the substring `"invoice"` inside that key name satisfied `classify()`'s
   regex before the test could reach the divergent case it was meant to
   force, so it would have silently passed without testing anything real.
   Fixed by choosing field names with no accidental regex collision.

### Verification
Real `PyPDF2` extraction, real regex matching, real async retry dispatch,
`astream` genuinely streaming node-by-node — verified via direct graph
calls and through the real HTTP route (`ASGITransport`, not a mock).

---

## Section 2 — Scope confirmation: does this genuinely close the gap?

Before building further, explicitly audited whether the plan
(checkpointing, tool-calling, HITL, multi-agent handoff) maps to real
"agent orchestration" JD language, or would just be box-checking on top of
a system too simple to justify it.

**Conclusion:** the plan covers persistence/checkpointing, tool-calling,
human-in-the-loop, and multi-agent coordination — genuinely substantive,
*if* each piece is built against a real need in the codebase rather than
forced. This governed every design decision below: several branches were
explicitly reconsidered or redesigned specifically because an initial
version would have been a "relabeled function," not real coordination.

**Parallel/fan-out execution** (a distinct orchestration pattern some JDs
call out) was explicitly scoped out — no genuine concurrent-agent case
exists in this pipeline's input space (one document → one classification →
one agent), and no artificial one was built just to claim the pattern.

---

## Section 3 — Critic, tool-calling, and human-in-the-loop (final design)

### Design evolution (real, not linear)
The original plan had the critic sitting between extraction and a
separate tool-calling node in a strict sequence. Reviewed against the
actual codebase and rejected: a critic that *always* hands off to the same
next step, with no branching, is a two-step pipeline wearing a
multi-agent costume — nothing about it requires two agents to exist.

**Final design:** the critic's confidence assessment drives a real
conditional branch — high confidence proceeds to `tool_calling`, low
confidence routes to `human_review` instead of guessing. This makes the
critic's judgment control what happens next (genuine coordination), gives
`human_review`'s interrupt a real trigger condition (not "pause before
every dispatch regardless of certainty"), and is built entirely on an
already-proven real bug (the intent-overwrite case from Section 1) rather
than a manufactured scenario.

**Human reviewer gets a genuine reject path, not approve-only:** rejection
loops back to the critic with feedback for reconsideration, rather than
the interrupt being a rubber stamp. This is the one loop in the graph.

### Nodes
- **`critic_node`** (`app/graphs/critic_agent.py`) — real second agent.
  Arbitrates disagreement between the classifier's regex-guessed intent
  and the format-agent's own content-derived intent (only `json_agent`
  produces one). Structured JSON output: `trusted_intent`, `confidence`,
  `note`. Accepts optional `human_feedback` for reconsideration passes.
- **`tool_calling_node`** (`app/graphs/tool_calling_agent.py`) — replaces
  `route_action`'s hardcoded if/elif entirely, including its dead
  `"policy"` branch, which simply no longer exists as a concept. Real
  function-calling: `post_to_crm`/`post_risk_alert` bound as tools, model
  decides at runtime which (if any) to call.
- **`human_review_node`** (`app/graphs/human_review.py`) — `interrupt()`
  gate. On resume, the entire node re-runs from the top (a real LangGraph
  semantic, not obvious from the name) — code before the interrupt runs
  twice, safe here since it's side-effect-free.

### Real bugs and findings
1. **Recursion limit does not fire across interrupt/resume boundaries —
   verified experimentally, changes what could honestly be claimed.**
   Isolated at the tightest possible limit (`recursion_limit=1`): a human
   can reject repeatedly and `GraphRecursionError` never raises, because
   `human_review_node` always calls `interrupt()` on its way back into the
   loop, and each interrupt/resume boundary resets LangGraph's
   per-invocation step budget. The loop is bounded by the interrupt
   itself (a human has to keep actively rejecting), not by
   `recursion_limit`. **Deliberately did not add an artificial ungated
   loop just to make the setting fire** — consistent with the standard set
   from the start of this step.
2. **Live finding, real model, first genuine attempt:** a document with
   the classifier's guess (`"Complaint"`) and no strong agent-derived
   intent to conflict with it still produced a correct `post_risk_alert`
   action, because `tool_calling_node` read the actual document content
   (a note mentioning GDPR/fraud concerns) rather than dispatching off the
   `intent` label alone. The **old hardcoded `route_action`** could never
   have caught this — its compliance-alert branch required
   `intent in {"regulation","policy"}` exactly, and this document's intent
   was `"Complaint"`. Concrete evidence the LLM-based approach isn't just
   a more flexible version of the same logic — it catches real cases the
   string-matched original structurally could not.

### Checkpointing decision
Postgres-backed (`AsyncPostgresSaver`), not `MemorySaver` — required
infrastructure for `interrupt()` to survive anything beyond the same
process's memory, not optional polish. Own dedicated database
(`mf_agent_checkpoints`), kept separate from any other project's Postgres
instance, matching the same separation already applied to AWS credentials
and Langfuse projects elsewhere in this build.

**Verified, not assumed:** persistence across a genuinely fresh connection
(a brand-new `AsyncPostgresSaver` instance, opened after the writing
connection fully closed) — confirmed a second, independent process can
pick up exactly where the first left off, for both a plain checkpoint and
a paused interrupt specifically.

---

## Section 4 — API wiring

`/process` can no longer always resolve synchronously once human review
exists — response envelope changed to `"status": "completed" |
"pending_review" | "error"`, a genuine breaking change, not slipped in
silently. Two new endpoints: `POST /review/{thread_id}` to submit a
decision, `GET /review/{thread_id}` to re-fetch a pending review
independently (via `graph.aget_state()`, not by re-invoking).

### Bugs found and fixed
1. **`httpx.ASGITransport` does not run FastAPI's lifespan events
   automatically** — checked its constructor signature directly before
   assuming, not after a failure. Tests manually enter
   `app.router.lifespan_context(app)`.
2. **`main.py` never called `load_dotenv()`** — `.env` values were present
   in the file but never actually loaded into the process environment.
   Real bug in the initial handover, caught by the first real startup
   attempt.
3. **`submit_review` accepted a resume on an already-completed thread —
   found via live testing, not the sandbox.** Original check only
   confirmed a checkpoint *existed* for a `thread_id`, not that it was
   actually paused at an interrupt. A Swagger request with placeholder
   values against a finished thread was silently accepted and returned
   `200`. Fixed by switching to `graph.aget_state(config)` and checking
   `.interrupts`, matching the check `get_review` already used correctly
   — two different ways of checking the same thing, unified to one.
   Reproduced deliberately afterward with a real completed `thread_id` and
   confirmed the fix returns a correct `400`.
4. **`thread_id` missing from completed responses** — only included when
   `pending_review`. Fixed so every response carries it, since it's also
   the seed for the Langfuse trace ID (Section 6) — without it, a
   completed run's trace was unreachable from the API response alone.

---

## Section 5 — Test suite and CI

No CI existed in this repo before this step. Built from scratch:
`.github/workflows/ci.yml`, plain `postgres:16` service (no pgvector
needed here — this project only uses Postgres for LangGraph checkpointing,
unlike the RAG project's vector search).

### Bugs found in existing tests (pre-existing, unrelated to this step's changes)
1. **`test_router.py` broken by the async conversion** — called
   `route_action(...)` synchronously with no `await`; `route_action`
   became `async def` in Section 1. `route_action` itself is now dead code
   in the live app (`tool_calling_node` replaced it) — kept and tested as
   documented legacy reference, an explicit decision, not an oversight.
2. **`test_router.py`'s risk-alert test asserted an outcome its own input
   could never produce.** `{"flag_total_exceeds": True}` doesn't match
   either of `route_action`'s real trigger conditions — this was wrong
   before the async conversion touched anything. Corrected to a real
   trigger case; added a second test covering the previously-untested
   regulation/compliance-terms branch.
3. **`test_agents.py`'s missing-fields test asserted behavior the code
   doesn't have.** `process_json`'s intent-detection requires `event` AND
   `id` both present just to classify something as `"Webhook"` — a
   payload missing `id` falls through to `"Unknown"`, whose schema has
   zero required fields, so nothing can ever be flagged missing. A partial
   webhook payload is invisible to validation precisely because it's too
   incomplete to be recognized as one. Documented as a known gap in
   `json_agent.py`, test corrected to assert real behavior — **not fixed**,
   since `json_agent`'s output feeds directly into `critic_node`, and
   changing it would require re-verifying everything already confirmed
   working.

### Coverage
18 tests: agent unit logic, legacy router logic, full graph-level tests
(all four format branches, malformed-input degradation, high-confidence
straight-through, low-confidence → approve, reject → loops back to critic
for real — critic call count asserted, not just outcome — recursion-limit
finding as a regression-protecting assertion, restart survival via a
genuinely fresh connection), and full HTTP-level API tests (real lifespan,
real `ASGITransport`, correct 404s on unknown/never-paused threads).

---

## Section 6 — Langfuse tracing

### Decision
Used `langfuse.langchain.CallbackHandler` — the LangChain/LangGraph-native
integration — instead of manual per-node instrumentation like the RAG
project's step 3. Verified this automatically traces every node in the
graph, including the conditional-edge routing functions themselves, with
zero manual wrapping code. A genuinely different, lower-effort tradeoff
than the RAG project's approach, appropriate specifically because this
app is built on LangGraph/LangChain (the RAG project's `stream_answer`
wasn't).

Separate Langfuse Cloud project from the RAG project's — same reasoning
already applied to Postgres and AWS credentials: keeps two genuinely
different systems' traces from mixing in one dashboard.

Accepted generic automatic span names/types (`critic`, `tool_calling`,
`human_review` — the actual function names) over adding manual semantic
type-tagging (`agent`/`tool`/`retriever`) on top. The real, hard-won value
here — full automatic node coverage plus a unified trace across a
human-approval pause — outweighs dashboard-icon polish, and partially
reintroducing manual wrapping would have undone some of the reason
automatic tracing was the better choice in the first place.

### Real bug found and fixed before it shipped
A fresh `CallbackHandler` on each separate `ainvoke()` call produces
**disconnected trace IDs by default** — confirmed experimentally with an
injected in-memory exporter before writing any production code, not
discovered via a failure. This would have meant a single logical request
that pauses for human approval showed up as two unrelated traces in the
dashboard. Fixed using Langfuse's own documented `create_trace_id(seed=...)`
helper, seeded with the checkpoint's `thread_id`, applied identically on
both `/process` and `/review/{thread_id}`'s callback construction.

### Verification
- Sandbox: confirmed via injected `InMemorySpanExporter` that two separate
  `ainvoke()` calls with the same seeded trace ID land as one trace, both
  through direct graph calls and through the real HTTP endpoints
  (`/process` → `pending_review` → `/review/{thread_id}` → `completed`).
- Live, real dashboard: confirmed a real trace (`b2845a6f...`) containing
  two `LangGraph` spans twelve seconds apart, correctly merged under one
  trace ID via the seeded `thread_id` — the mechanism working with real
  API calls, not just mocked ones.
- **Known, accepted gap:** `Cost ($)` and `Time to First Token` don't
  populate in the dashboard — the generic LangChain/LangGraph callback
  integration doesn't parse Groq's token-usage metadata the way a
  native/manual wrapper would. Not fixed; a real limitation of choosing
  the automatic-tracing tradeoff, documented rather than silently absent.

---

## Known limitations (said out loud on purpose)

- **`json_agent.py`'s Webhook-detection gap** (Section 5) is real and
  unfixed — a partial webhook payload missing `id` is invisible to
  validation. Deliberately left alone: fixing it changes what `critic_node`
  sees for every JSON document with partial `event`/`id` fields, which
  would require re-verifying work already confirmed correct.
- **Live low-confidence HITL trigger not yet observed in production** at
  time of writing. The mechanism itself is proven correct — real
  interrupt, real resume, real reject-loop, real restart-survival, all
  verified against real Postgres/LangGraph — but every live document
  tried so far has resolved confidently on the real model's first pass.
  Worth stating plainly rather than implying a live low-confidence run has
  been observed when it hasn't.
- **No cost/token tracking in Langfuse** for this app specifically — see
  Section 6.
- **`route_action()` is dead code**, kept intentionally as documented
  legacy reference (explicit decision), not because anything in the live
  app still calls it.

## Skills demonstrated

Stateful agent orchestration (LangGraph), Postgres-backed checkpointing
with verified cross-restart persistence, real tool-calling/function-calling
agents (not hardcoded branching), human-in-the-loop workflows with a
genuine reject-and-reconsider loop, multi-agent coordination via a critic
whose judgment drives real conditional routing, LangGraph/LangChain-native
observability (Langfuse), and a fully tested (pytest) CI pipeline covering
every conditional branch — including forced tool-calls, forced interrupts,
and the recursion-limit boundary — built from scratch for a repo that had
none before.