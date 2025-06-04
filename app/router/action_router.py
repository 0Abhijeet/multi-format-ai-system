from app.utils.retry_utils import retry_action

def post_to_crm(data):
    print("[Simulated] POST /crm/escalate", data)
    return "escalated"

def post_risk_alert(data):
    print("[Simulated] POST /risk_alert", data)
    return "risk_alert_sent"

def route_action(agent_output):
    intent = agent_output.get("intent", "").lower()
    action = agent_output.get("action")

    # Define wrapped actions for retry
    def escalate():
        return post_to_crm(agent_output)

    def alert():
        return post_risk_alert(agent_output)

    # Email complaints: escalate if tone and urgency are high
    if action == "escalate":
        return retry_action(escalate)

    # Invoice or PDF: flag if amount > 10,000
    if intent == "invoice" and agent_output.get("data", {}).get("amount", 0) > 10000:
        return retry_action(alert)

    # PDF policy: flag if "GDPR", "FDA", etc. terms found
    if intent in {"regulation", "policy"} and agent_output.get("compliance_terms"):
        return retry_action(alert)

    return "no_action"
