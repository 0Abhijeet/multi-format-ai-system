from app.utils.retry_utils import retry_action

def post_to_crm(data):
    print("[Simulated] POST /crm/escalate", data)
    return "escalated"

def post_risk_alert(data):
    print("[Simulated] POST /risk_alert", data)
    return "risk_alert_sent"

async def route_action(agent_output):
    """
    NOTE: this function is now UNUSED / dead code -- tool_calling_agent.py
    replaces it entirely with real LLM-decided tool calls. Kept only
    because post_to_crm/post_risk_alert below are still reused as the
    actual tool implementations. Left in place rather than deleted so the
    original logic (including its dead "policy" branch) stays visible for
    reference/build-log purposes; delete if you'd rather not carry it.
    """
    intent = agent_output.get("intent", "").lower()
    action = agent_output.get("action")

    async def escalate():
        return await retry_action(lambda: post_to_crm(agent_output))

    async def alert():
        return await retry_action(lambda: post_risk_alert(agent_output))

    if action == "escalate":
        return await escalate()

    if intent == "invoice" and agent_output.get("data", {}).get("amount", 0) > 10000:
        return await alert()

    if intent in {"regulation", "policy"} and agent_output.get("compliance_terms"):
        return await alert()

    return "no_action"