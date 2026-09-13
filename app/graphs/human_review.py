"""
Human-in-the-loop node (requirement #4). Fires ONLY when the critic
couldn't confidently resolve the intent conflict -- a real trigger
condition, not "pause before every dispatch regardless of whether
anything's actually uncertain."

Genuine reject path (not approve-only): a human can reject the critic's
proposed resolution with feedback, which loops back to critic_node for
reconsideration -- see requirement #6 (recursion limit) for why this loop
needs bounding, and app/graphs/pipeline.py for the actual limit + what
happens when it's hit.

interrupt() halts execution here and surfaces `value` to whatever client
is running the graph. On resume (Command(resume=...)), THIS ENTIRE NODE
RE-RUNS FROM THE TOP -- interrupt() then returns the resume value instead
of raising. Code before the interrupt() call therefore runs twice (once
to hit the interrupt, once on resume) -- side-effect-free here, so safe,
but a real LangGraph semantic worth knowing, not obvious from the name.
"""
from langgraph.types import interrupt


async def human_review_node(state: dict) -> dict:
    agent_result = state.get("agent_result") or {}
    classification = state.get("classification") or {}

    decision = interrupt({
        "reason": "Critic flagged low confidence resolving the intent conflict",
        "critic_note": state.get("critic_note"),
        "classifier_intent": classification.get("intent"),
        "agent_result": agent_result,
    })

    if isinstance(decision, dict) and decision.get("approved"):
        result = dict(agent_result)
        if "approved_intent" in decision:
            result["intent"] = decision["approved_intent"]
        return {"agent_result": result, "confidence": "human-approved", "human_feedback": None}

    feedback = decision.get("feedback", "Human reviewer rejected without specific feedback") if isinstance(decision, dict) else "Human reviewer rejected"
    return {"confidence": None, "human_feedback": feedback}