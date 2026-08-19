"""
LangGraph ReAct agent workflow.

The graph follows the standard ReAct (Reason + Act) loop:
  user message → agent node → tool node → agent node → … → END

The agent node calls the Ollama-backed LLM with the bound tools.
The tool node executes whichever tools the LLM requested.
"""
import logging
from typing import AsyncIterator

from langchain_core.messages import HumanMessage
from langchain_ollama import ChatOllama
from langgraph.graph import END, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode

from app.config import settings
from app.agent.tools import TOOLS

logger = logging.getLogger(__name__)


def _build_graph():
    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0,
    ).bind_tools(TOOLS)

    tool_node = ToolNode(TOOLS)

    def agent_node(state: MessagesState):
        try:
            response = llm.invoke(state["messages"])
        except Exception as exc:
            logger.error("LLM invocation failed: %s", exc)
            from langchain_core.messages import AIMessage
            response = AIMessage(
                content=(
                    f"I encountered an error while processing your request: {exc}. "
                    "Please check that the Ollama service is running and accessible."
                )
            )
        return {"messages": [response]}

    def should_continue(state: MessagesState) -> str:
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue)
    graph.add_edge("tools", "agent")

    return graph.compile()


_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


def run_agent(machine_id: str, error_code: str) -> str:
    """Run the agent synchronously and return the final answer."""
    query = (
        f"A maintenance issue has been reported for machine '{machine_id}' "
        f"with error code '{error_code}'. "
        "Please: (1) retrieve the maintenance history for this machine, "
        "(2) search the maintenance manual for guidance on this error, "
        "(3) check available spare parts, "
        "(4) provide a repair recommendation, and "
        "(5) create a maintenance ticket if one does not already exist."
    )
    graph = get_graph()
    result = graph.invoke({"messages": [HumanMessage(content=query)]})
    return result["messages"][-1].content


async def stream_agent(machine_id: str, error_code: str) -> AsyncIterator[str]:
    """Stream agent events as Server-Sent Event data strings."""
    query = (
        f"A maintenance issue has been reported for machine '{machine_id}' "
        f"with error code '{error_code}'. "
        "Please: (1) retrieve the maintenance history for this machine, "
        "(2) search the maintenance manual for guidance on this error, "
        "(3) check available spare parts, "
        "(4) provide a repair recommendation, and "
        "(5) create a maintenance ticket if one does not already exist."
    )
    graph = get_graph()
    async for event in graph.astream({"messages": [HumanMessage(content=query)]}):
        for node_name, node_output in event.items():
            messages = node_output.get("messages", [])
            for msg in messages:
                content = getattr(msg, "content", None)
                if content:
                    yield f"[{node_name}] {content}"
