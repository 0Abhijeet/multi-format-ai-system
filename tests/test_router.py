from app.router.action_router import route_action

def test_route_action_escalate():
    agent_output = {"action": "escalate"}
    result = route_action(agent_output)
    assert result == "escalated"

def test_route_action_risk_alert():
    agent_output = {"flag_total_exceeds": True}
    result = route_action(agent_output)
    assert result == "risk_alert_sent"

def test_route_action_no_action():
    agent_output = {}
    result = route_action(agent_output)
    assert result == "no_action"
