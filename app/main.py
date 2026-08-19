"""REST API: запуск агента (синхронно + SSE-стрим), чтение БД, health."""

import json
import logging

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Machine, MaintenanceTicket, SparePart

app = FastAPI(title="Industrial Agent", version="1.0")


class AgentRunRequest(BaseModel):
    message: str = Field(description="Сообщение оператора, например 'Conveyor Line 4 stopped. Error E142'")
    thread_id: str = "default"
    stream: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/machines")
def list_machines(limit: int = 50):
    with SessionLocal() as s:
        rows = s.execute(select(Machine).order_by(Machine.machine_id).limit(limit)).scalars().all()
    return [{
        "machine_id": m.machine_id,
        "machine_name": m.machine_name,
        "location": m.location,
        "status": m.status,
        "last_service": str(m.last_service),
    } for m in rows]


@app.get("/spare_parts")
def list_spare_parts(limit: int = 100):
    with SessionLocal() as s:
        rows = s.execute(select(SparePart).order_by(SparePart.part_number).limit(limit)).scalars().all()
    return [{
        "part_number": p.part_number,
        "name": p.name,
        "quantity": p.quantity,
        "location": p.location,
    } for p in rows]


@app.get("/tickets")
def list_tickets(limit: int = 50):
    with SessionLocal() as s:
        rows = s.execute(select(MaintenanceTicket).order_by(MaintenanceTicket.ticket_id.desc()).limit(limit)).scalars().all()
    return [{
        "ticket_id": t.ticket_id,
        "machine_id": t.machine_id,
        "error_code": t.error_code,
        "title": t.title,
        "priority": t.priority,
        "status": t.status,
        "created_at": str(t.created_at),
    } for t in rows]


@app.post("/agent/run")
async def agent_run(req: AgentRunRequest):
    from app.agent.graph import get_graph

    graph = await get_graph()
    config = {"configurable": {"thread_id": req.thread_id}}
    result = await graph.ainvoke({"messages": [("human", req.message)]}, config)

    final = result["messages"][-1].content
    return {
        "thread_id": req.thread_id,
        "ticket_id": result.get("ticket_id"),
        "ticket_error": result.get("ticket_error"),
        "recommendation": final,
    }


@app.post("/agent/stream")
async def agent_stream(req: AgentRunRequest):
    """SSE-поток шагов агента."""
    from app.agent.graph import get_graph

    graph = await get_graph()
    config = {"configurable": {"thread_id": req.thread_id}}

    async def gen():
        try:
            yield "data: " + json.dumps({"type": "start"}, ensure_ascii=False) + "\n\n"
            async for chunk in graph.astream({"messages": [("human", req.message)]}, config):
                for node, payload in chunk.items():
                    if node == "agent":
                        msg = payload["messages"][-1]
                        for tc in getattr(msg, "tool_calls", []):
                            yield "data: " + json.dumps({
                                "type": "tool_call",
                                "name": tc["name"],
                                "args": tc["args"],
                            }, ensure_ascii=False) + "\n\n"
                    elif node == "tools":
                        for tm in payload["messages"]:
                            yield "data: " + json.dumps({
                                "type": "tool_result",
                                "name": tm.name,
                                "content": tm.content[:800],
                                "status": getattr(tm, "status", "success"),
                            }, ensure_ascii=False) + "\n\n"

            state = await graph.aget_state(config)
            ticket_id = state.values.get("ticket_id")
            ticket_error = state.values.get("ticket_error")
            if state.values.get("ticket_failed"):
                # Реальная техническая неудача (например, ValidationError в tool call).
                yield "data: " + json.dumps({
                    "type": "error",
                    "reason": "create_maintenance_ticket did not succeed",
                    "ticket_error": ticket_error,
                }, ensure_ascii=False) + "\n\n"
            else:
                # ticket_id может быть None легитимно (например, машина не найдена) —
                # это не ошибка стрима, а контролируемый бизнес-исход.
                yield "data: " + json.dumps({
                    "type": "done",
                    "ticket_id": ticket_id,
                    "ticket_error": ticket_error,
                }, ensure_ascii=False) + "\n\n"
        except Exception as exc:
            # Стрим не должен обрываться молча (например, при транзиентном сбое БД):
            # клиент всегда получает явное финальное событие, причина остаётся в логах.
            logging.getLogger(__name__).exception("agent_stream failed for thread_id=%s", req.thread_id)
            yield "data: " + json.dumps({
                "type": "error",
                "reason": "internal_error",
                "detail": str(exc),
            }, ensure_ascii=False) + "\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

