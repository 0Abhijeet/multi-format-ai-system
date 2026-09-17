# Facilities Maintenance Triage Agent

*This project began as a general-purpose document classifier and router; the sections below describe how it was adapted specifically for DivyaSree's facilities/co-living context — see the written note for what's original architecture versus what was built new for this problem.*

A document-intake pipeline built as a real LangGraph state machine: a maintenance ticket comes in — a resident complaint via email, a structured event from a facilities ticketing system, or a vendor's inspection/invoice report — and the system classifies it, extracts structured data, and decides what to do: escalate to the facilities manager, dispatch a vendor, or flag for cost approval, using an LLM-driven critic and tool-calling agent, not hardcoded rules.

## What this demonstrates

- Adapted an existing general-purpose classifier/router into a domain-specific triage system — reframing input channels, extraction fields, and dispatch logic for facilities/co-living operations, without touching the underlying orchestration
- Real tool-calling agent that decides at runtime whether to escalate or dispatch a vendor, based on actual ticket content — not a hardcoded intent-label lookup
- A genuine second agent (a critic) whose confidence assessment drives real conditional routing, reviewed and redesigned mid-build specifically to avoid a fake multi-agent pattern
- **Cost-threshold human approval**: any ticket with an estimated repair/vendor cost above $10,000 requires facilities-manager sign-off before dispatch, regardless of how confident the AI is — a real business rule, not a generic confidence gate
- Postgres-backed checkpointing, verified to survive an actual process restart — a paused approval genuinely isn't lost
- Human-in-the-loop with a real reject-and-reconsider loop, not a rubber stamp
- Full pytest suite (18 tests) and CI, covering every conditional branch including the new cost-gate logic

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI (async) |
| Orchestration | LangGraph (`StateGraph`, async nodes, conditional edges, `interrupt()`) |
| Checkpointing | PostgreSQL via `langgraph-checkpoint-postgres` |
| LLM | Groq (critic agent + tool-calling agent) |
| Observability | Langfuse (LangChain/LangGraph-native tracing) |
| Testing | pytest, pytest-asyncio, run against a real Postgres instance |
| CI/CD | GitHub Actions |

## Architecture decisions (and why)

| Decision | Reasoning |
|---|---|
| Reused an existing classifier/router rather than building from scratch | The orchestration layer (graph, checkpointing, tool-calling, HITL) was already solved and verified; adapting it let the available time go into what was actually new to this problem — the domain reframing and the cost-threshold logic |
| Cost-threshold gate as an *addition* to the confidence gate, not a replacement | Only ticket types with an extractable cost figure (vendor invoices) have anything to threshold — resident complaints have no cost field, so they correctly keep the original confidence-only gate. A universal cost check would have been dishonest about what the data actually supports |
| Critic's confidence drives a real conditional branch | An earlier design where the critic always proceeded to the same next step was assessed as a two-step pipeline wearing a multi-agent costume — redesigned before building further |
| Human reviewer gets a genuine reject path, not approve-only | Makes the interrupt an actual gate, not a rubber stamp |

## Known limitations

Said out loud on purpose:

- Rejecting a cost-threshold approval currently routes back through the same intent-reconsideration loop as an intent disagreement — a real simplification for this project's scope, not a production-ready distinction between "reconsider the classification" and "don't approve this cost," which would need a separate rejection pathway
- Live low-confidence trigger not yet observed on every input tried — the mechanism is fully verified (real interrupt, resume, reject-loop, restart-survival), but confidence resolution depends on the model's actual judgment per document
- No cost/token tracking in the Langfuse dashboard — the generic LangChain callback integration doesn't parse Groq's token usage the way a native wrapper would

## Local development

```bash
cp .env.example .env   # GROQ_API_KEY, DATABASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
```

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

Full build log and design-decision reasoning: [`PROJECT_DETAILS.md`](./Project_docs/PROJECT_DETAILS.md)