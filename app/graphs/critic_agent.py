"""
Real second agent (per requirement #5, final confirmed shape): arbitrates
disagreement between the classifier's regex-guessed intent and the
format-agent's own content-derived intent (only json_agent produces one --
email/pdf agents don't set their own "intent" key, so for those formats
the critic is validating the classifier's guess in isolation, not
resolving a conflict). This is a genuinely different question than either
upstream signal answers: they each produce ONE signal; the critic
arbitrates between two, or validates one when there's only one to check.

Runs BEFORE the old merge_classifier_intent step (which this replaces
entirely) -- it has to see the agent's ORIGINAL intent before anything
overwrites it, which is exactly the bug this whole redesign exists to fix.

Accepts optional human_feedback in state -- set when human_review_node
rejects a prior resolution and loops back here for reconsideration (see
human_review.py). Included in the prompt so a second pass is genuinely
informed, not just a repeat of the same reasoning.
"""
import json

from app.graphs.llm_client import get_groq_client, MODEL

CRITIC_SYSTEM_PROMPT = """You are a critic agent reviewing a document-processing pipeline's output.

You are given:
- The classifier's guessed intent (from crude keyword regex matching over raw bytes -- unreliable)
- The format-specific agent's own derived intent, if it produced one (more reliable when present, since it comes from actually parsing structured content)
- The agent's full extracted result
- Optionally, feedback from a human reviewer who rejected a previous resolution attempt

Decide which intent should actually be trusted, and how confident you are.
If there is no agent-derived intent to compare against, just judge whether
the classifier's guess is plausible given the extracted result.

Respond ONLY with JSON in this exact shape:
{"trusted_intent": "<string>", "confidence": "high" or "low", "note": "<one sentence explaining your reasoning>"}

Use "low" confidence when the classifier and agent genuinely disagree and
you cannot confidently resolve which is right from the data given -- this
routes to a human reviewer, so only use "low" when that's genuinely warranted."""


async def critic_node(state: dict) -> dict:
    classification = state.get("classification") or {}
    agent_result = state.get("agent_result") or {}
    human_feedback = state.get("human_feedback")

    classifier_intent = classification.get("intent")
    agent_own_intent = agent_result.get("intent")

    user_prompt = (
        f"Classifier's guessed intent: {classifier_intent!r}\n"
        f"Agent's own derived intent (if any): {agent_own_intent!r}\n"
        f"Agent's full extracted result: {json.dumps(agent_result)}"
    )
    if human_feedback:
        user_prompt += f"\n\nA human reviewer REJECTED a previous resolution attempt with this feedback: {human_feedback!r}\nReconsider taking this into account."

    client = get_groq_client()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": CRITIC_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    parsed = json.loads(response.choices[0].message.content)

    result = dict(agent_result)
    result["intent"] = parsed["trusted_intent"]

    return {
        "agent_result": result,
        "confidence": parsed["confidence"],
        "critic_note": parsed["note"],
        "human_feedback": None,
    }