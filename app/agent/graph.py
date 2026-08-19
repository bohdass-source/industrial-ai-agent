"""LangGraph: agent -> tools -> finalize, чекпойнтер в PostgreSQL."""

import json
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from psycopg.rows import dict_row

from app.agent import tools as tools_module
from app.agent.prompts import SYSTEM_PROMPT
from app.config import settings


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    machine_name: Optional[str]
    error_code: Optional[str]
    ticket_id: Optional[int]
    ticket_error: Optional[str]
    ticket_failed: Optional[bool]
    recommendation: Optional[str]


TOOLS = [
    tools_module.get_machine_info,
    tools_module.search_manual,
    tools_module.get_machine_history,
    tools_module.check_spare_parts,
    tools_module.create_maintenance_ticket,
]


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature,
    )


def build_graph(checkpointer=None):
    llm = _llm().bind_tools(TOOLS)
    tool_node = ToolNode(TOOLS)

    def agent_node(state: AgentState) -> dict:
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        return {"messages": [llm.invoke(messages)]}

    def tools_node(state: AgentState) -> dict:
        updates: dict = {}

        for m in reversed(state["messages"]):
            if isinstance(m, AIMessage):
                for tc in m.tool_calls:
                    args = tc.get("args") or {}
                    if args.get("machine_name") and "machine_name" not in updates:
                        updates["machine_name"] = args["machine_name"]
                    if args.get("error_code") and "error_code" not in updates:
                        updates["error_code"] = args["error_code"]
                break

        result = tool_node.invoke(state)
        updates["messages"] = result["messages"]

        for msg in result["messages"]:
            if isinstance(msg, ToolMessage) and msg.name == "create_maintenance_ticket":
                if getattr(msg, "status", None) == "error":
                    updates["ticket_error"] = msg.content
                    updates["ticket_failed"] = True
                    continue
                try:
                    data = json.loads(msg.content)
                    if isinstance(data, dict) and data.get("ticket_id"):
                        updates["ticket_id"] = data["ticket_id"]
                        updates["ticket_error"] = None
                        updates["ticket_failed"] = False
                    elif isinstance(data, dict) and data.get("error"):
                        # Контролируемый отказ (не найдена машина) — это не сбой инструмента.
                        updates["ticket_error"] = data.get("message") or data["error"]
                except Exception:
                    pass
        return updates

    def route_after_agent(state: AgentState) -> str:
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", None) else "finalize"

    def finalize_node(state: AgentState) -> dict:
        updates: dict = {}
        ticket_id = state.get("ticket_id")
        if ticket_id is None:
            res = tools_module.create_maintenance_ticket.invoke({
                "machine_name": state.get("machine_name") or "Unknown",
                "error_code": state.get("error_code"),
                "title": (f"Авто-тикет (страховка): {state.get('error_code') or 'без кода'} "
                          f"на {state.get('machine_name') or 'неизвестной машине'}"),
                "description": "LLM не создал заявку в ходе диалога — тикет создан "
                               "автоматически на финальном этапе графа.",
                "priority": "medium",
            })
            try:
                data = json.loads(res)
                ticket_id = data.get("ticket_id")
                ticket_error = data.get("message") or data.get("error") if ticket_id is None else None
            except Exception:
                ticket_id, ticket_error = None, state.get("ticket_error")
            updates["ticket_id"] = ticket_id
            updates["ticket_error"] = ticket_error
            updates["ticket_failed"] = False

        recommendation = None
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and msg.content:
                recommendation = msg.content
                break
        updates["recommendation"] = recommendation
        return updates

    g = StateGraph(AgentState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.add_node("finalize", finalize_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route_after_agent, {"tools": "tools", "finalize": "finalize"})
    g.add_edge("tools", "agent")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


_pool = None
_graph = None


async def get_graph():
    global _pool, _graph
    if _graph is not None:
        return _graph

    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from psycopg_pool import AsyncConnectionPool

    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=settings.checkpointer_dsn,
            max_size=20,
            open=False,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
            },
        )
        await _pool.open()
        checkpointer = AsyncPostgresSaver(_pool)
        await checkpointer.setup()
    else:
        checkpointer = AsyncPostgresSaver(_pool)

    _graph = build_graph(checkpointer)
    return _graph
