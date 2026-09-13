import pytest
from app.router.action_router import route_action

# route_action() is now UNUSED in the live app (tool_calling_node replaced
# it -- see app/graphs/tool_calling_agent.py). Kept and tested as documented
# legacy reference, per explicit decision, not because anything still calls
# it in production.
#
# Converted to async tests: route_action became async def in step 4.1
# (its retry_action dependency needed asyncio.sleep instead of blocking
# time.sleep). The original sync `result = route_action(...)` calls would
# fail immediately now.

@pytest.mark.asyncio
async def test_route_action_escalate():
    agent_output = {"action": "escalate"}
    result = await route_action(agent_output)
    assert result == "escalated"


@pytest.mark.asyncio
async def test_route_action_risk_alert_invoice():
    # BUG FOUND while fixing this file: the original test used
    # agent_output = {"flag_total_exceeds": True}, expecting "risk_alert_sent".
    # But route_action's actual logic never checks "flag_total_exceeds" at
    # all -- its two risk-alert conditions are (a) intent=="invoice" AND
    # data.amount>10000, or (b) intent in {"regulation","policy"} AND
    # compliance_terms present. The original input satisfied neither, so it
    # was already asserting an outcome the code couldn't produce -- this
    # was wrong before the async conversion touched anything. Corrected to
    # actually exercise the invoice>10000 branch.
    agent_output = {"intent": "invoice", "data": {"amount": 15000}}
    result = await route_action(agent_output)
    assert result == "risk_alert_sent"


@pytest.mark.asyncio
async def test_route_action_risk_alert_regulation():
    # The OTHER risk-alert branch, not covered by the original test at all.
    # "policy" (also in the checked set) is dead -- classify() never
    # produces it, only "Regulation" -- so it's not exercised here since
    # it's structurally unreachable (see app/graphs/pipeline.py docstring).
    agent_output = {"intent": "regulation", "compliance_terms": ["GDPR"]}
    result = await route_action(agent_output)
    assert result == "risk_alert_sent"


@pytest.mark.asyncio
async def test_route_action_no_action():
    agent_output = {}
    result = await route_action(agent_output)
    assert result == "no_action"