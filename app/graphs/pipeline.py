"""
Step 4 -- full graph. Evolved from the 4.1 linear port:
classify -> route by format -> agent -> critic -> [tool_calling | human_review] -> END

merge_classifier_intent and dispatch_action (4.1) are REMOVED, not kept
alongside the new nodes -- critic_node replaces the blind intent-overwrite
with real arbitration, and tool_calling_node replaces route_action's
hardcoded if/elif (including its dead "policy" branch, which no longer
exists as a concept here) with real LLM-decided tool calls.

The only loop in this graph: human_review_node's reject path sends
execution back to critic_node for reconsideration. Bounded by an explicit
recursion_limit (see build_graph) -- see test_pipeline_llm.py for what
actually happens when it's hit (documented finding: it does NOT fire
across interrupt/resume boundaries -- see build log).
"""
from typing import TypedDict, Optional

from langgraph.graph import StateGraph, START, END

from app.agents.classifier_agent import classify
from app.agents.email_agent import process_email
from app.agents.json_agent import process_json
from app.agents.pdf_agent import process_pdf
from app.graphs.critic_agent import critic_node
from app.graphs.tool_calling_agent import tool_calling_node
from app.graphs.human_review import human_review_node

DEFAULT_RECURSION_LIMIT = 10


class GraphState(TypedDict):
    raw_content: bytes
    filename: str
    classification: Optional[dict]
    agent_result: Optional[dict]
    action_result: Optional[str]
    confidence: Optional[str]
    critic_note: Optional[str]
    human_feedback: Optional[str]


async def classify_input(state: GraphState) -> dict:
    classification = classify(state["raw_content"], state["filename"])
    return {"classification": classification}


def _route_by_format(state: GraphState) -> str:
    fmt = state["classification"]["format"]
    return {
        "Email": "email_agent",
        "JSON": "json_agent",
        "PDF": "pdf_agent",
    }.get(fmt, "unsupported")


async def email_agent_node(state: GraphState) -> dict:
    try:
        return {"agent_result": process_email(state["raw_content"])}
    except Exception as e:
        return {"agent_result": {"error": str(e)}}


async def json_agent_node(state: GraphState) -> dict:
    try:
        return {"agent_result": process_json(state["raw_content"])}
    except Exception as e:
        return {"agent_result": {"error": str(e)}}


async def pdf_agent_node(state: GraphState) -> dict:
    try:
        return {"agent_result": process_pdf(state["raw_content"])}
    except Exception as e:
        return {"agent_result": {"error": str(e)}}


async def unsupported_node(state: GraphState) -> dict:
    return {"agent_result": {"error": "Unsupported format"}}


def _route_by_confidence(state: GraphState) -> str:
    return "tool_calling" if state.get("confidence") == "high" else "human_review"


def _route_after_human_review(state: GraphState) -> str:
    return "tool_calling" if state.get("confidence") == "human-approved" else "critic"


def build_graph(checkpointer=None):
    graph = StateGraph(GraphState)

    graph.add_node("classify_input", classify_input)
    graph.add_node("email_agent", email_agent_node)
    graph.add_node("json_agent", json_agent_node)
    graph.add_node("pdf_agent", pdf_agent_node)
    graph.add_node("unsupported", unsupported_node)
    graph.add_node("critic", critic_node)
    graph.add_node("tool_calling", tool_calling_node)
    graph.add_node("human_review", human_review_node)

    graph.add_edge(START, "classify_input")
    graph.add_conditional_edges(
        "classify_input",
        _route_by_format,
        {
            "email_agent": "email_agent",
            "json_agent": "json_agent",
            "pdf_agent": "pdf_agent",
            "unsupported": "unsupported",
        },
    )
    for agent_node in ["email_agent", "json_agent", "pdf_agent", "unsupported"]:
        graph.add_edge(agent_node, "critic")

    graph.add_conditional_edges(
        "critic",
        _route_by_confidence,
        {"tool_calling": "tool_calling", "human_review": "human_review"},
    )
    graph.add_conditional_edges(
        "human_review",
        _route_after_human_review,
        {"tool_calling": "tool_calling", "critic": "critic"},
    )
    graph.add_edge("tool_calling", END)

    return graph.compile(checkpointer=checkpointer)