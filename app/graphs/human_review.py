from langgraph.types import interrupt

COST_THRESHOLD = 10000  # matches the existing invoice risk-alert threshold already in the codebase


def _build_interrupt_payload(state: dict) -> dict:
    """
    Tags WHY the interrupt fired -- a cost-threshold approval and an
    intent-arbitration disagreement are different questions for the human
    reviewer, even though both use the same interrupt()/reject-loop
    mechanism. Real simplification for this artifact's scope: rejection on
    either reason still loops back to critic_node, rather than adding a
    second reject pathway.
    """
    agent_result = state.get("agent_result") or {}
    classification = state.get("classification") or {}
    estimated_cost = agent_result.get("invoice_total", 0) or 0

    if estimated_cost > COST_THRESHOLD:
        reason = "cost_threshold_exceeded"
        detail = f"Estimated cost ${estimated_cost:,.2f} exceeds the ${COST_THRESHOLD:,} auto-approval threshold."
    else:
        reason = "intent_conflict"
        detail = state.get("critic_note")

    return {
        "reason": reason,
        "detail": detail,
        "estimated_cost": estimated_cost if estimated_cost else None,
        "classifier_intent": classification.get("intent"),
        "agent_result": agent_result,
    }


async def human_review_node(state: dict) -> dict:
    agent_result = state.get("agent_result") or {}

    decision = interrupt(_build_interrupt_payload(state))

    if isinstance(decision, dict) and decision.get("approved"):
        result = dict(agent_result)
        if "approved_intent" in decision:
            result["intent"] = decision["approved_intent"]
        return {"agent_result": result, "confidence": "human-approved", "human_feedback": None}

    feedback = decision.get("feedback", "Human reviewer rejected without specific feedback") if isinstance(decision, dict) else "Human reviewer rejected"
    return {"confidence": None, "human_feedback": feedback}