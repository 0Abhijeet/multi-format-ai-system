"""
Real tool-calling / function-calling node (requirement #3, built first per
priority). Replaces app/router/action_router.py's hardcoded if/elif chain
entirely -- including its dead "policy" branch, which simply no longer
exists as a concept here, since there's no more string-matching to have a
dead branch in. The LLM decides at runtime which tool(s) to call, if any,
based on the actual data -- not a hand-designed conditional.

post_to_crm/post_risk_alert/retry_action are UNCHANGED from the original --
they become the real tool implementations this node calls, not replaced.
"""
import json

from app.graphs.llm_client import get_groq_client, MODEL
from app.router.action_router import post_to_crm, post_risk_alert
from app.utils.retry_utils import retry_action

TOOL_CALLING_SYSTEM_PROMPT = """You decide what action, if any, to take on a processed document.

Available tools:
- post_to_crm: escalate to the CRM for human follow-up. Use for angry/urgent customer complaints (tone=angry, urgency=high, or action=escalate in the data).
- post_risk_alert: send a compliance/risk alert. Use for invoices with amount > $10,000, or documents containing regulatory compliance terms (GDPR, FDA).

Call zero, one, or both tools based only on the data given. Do not call a tool if neither condition is clearly met."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "post_to_crm",
            "description": "Escalate this item to the CRM system for human follow-up. Use for angry/urgent customer complaints.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_risk_alert",
            "description": "Send a risk/compliance alert. Use for invoice amounts over $10,000 or documents containing GDPR/FDA compliance terms.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

_TOOL_IMPL = {
    "post_to_crm": post_to_crm,
    "post_risk_alert": post_risk_alert,
}


async def tool_calling_node(state: dict) -> dict:
    agent_result = state.get("agent_result") or {}

    client = get_groq_client()
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": TOOL_CALLING_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(agent_result)},
        ],
        tools=TOOLS,
        tool_choice="auto",
    )
    message = response.choices[0].message

    calls_made = []
    if message.tool_calls:
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            impl = _TOOL_IMPL.get(name)
            if impl is None:
                continue
            result = await retry_action(lambda impl=impl: impl(agent_result))
            calls_made.append({"tool": name, "result": result})

    action_result = ", ".join(c["tool"] for c in calls_made) if calls_made else "no_action"
    return {"action_result": action_result}