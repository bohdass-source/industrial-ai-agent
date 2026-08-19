import asyncio
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.agent.workflow import run_agent, stream_agent

logger = logging.getLogger(__name__)
router = APIRouter()


class AgentRequest(BaseModel):
    machine_id: str
    error_code: Optional[str] = "UNKNOWN"


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.post("/agent/run")
async def agent_run(request: AgentRequest):
    """Run the maintenance agent and return the full response."""
    try:
        result = await asyncio.to_thread(run_agent, request.machine_id, request.error_code)
        return {"machine_id": request.machine_id, "error_code": request.error_code, "response": result}
    except Exception as exc:
        logger.error("agent/run error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Agent execution failed: {exc}"},
        )


@router.post("/agent/stream")
async def agent_stream(request: AgentRequest):
    """Stream the maintenance agent's step-by-step reasoning as SSE."""
    async def event_generator():
        try:
            async for chunk in stream_agent(request.machine_id, request.error_code):
                yield f"data: {chunk}\n\n"
        except Exception as exc:
            logger.error("agent/stream error: %s", exc)
            yield f"data: ERROR: {exc}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
