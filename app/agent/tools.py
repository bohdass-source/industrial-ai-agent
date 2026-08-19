"""
LangGraph agent tools for the industrial maintenance agent.

Each tool returns a plain string so the LLM can include it in the next
reasoning step.  All database I/O uses synchronous SQLAlchemy sessions
(the FastAPI routes run these in a thread pool via asyncio.to_thread).
"""
import json
import logging
from datetime import datetime

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.db.database import (
    MaintenanceHistory,
    MaintenanceTicket,
    ManualChunk,
    SparePart,
    engine,
)

logger = logging.getLogger(__name__)


@tool
def get_maintenance_history(machine_id: str) -> str:
    """Retrieve past maintenance records for a given machine_id."""
    try:
        with Session(engine) as session:
            rows = (
                session.query(MaintenanceHistory)
                .filter(MaintenanceHistory.machine_id == machine_id)
                .order_by(MaintenanceHistory.recorded_at.desc())
                .limit(10)
                .all()
            )
        if not rows:
            return f"No maintenance history found for machine '{machine_id}'."
        items = []
        for r in rows:
            items.append(
                f"[{r.recorded_at.date()}] Error {r.error_code}: {r.description} "
                f"→ Resolution: {r.resolution or 'N/A'} (Technician: {r.technician or 'unknown'})"
            )
        return "\n".join(items)
    except Exception as exc:
        logger.error("get_maintenance_history error: %s", exc)
        return f"Error retrieving maintenance history: {exc}"


@tool
def search_manual(machine_id: str, query: str) -> str:
    """Search maintenance manual chunks for a machine using keyword matching (RAG fallback)."""
    try:
        with Session(engine) as session:
            rows = (
                session.query(ManualChunk)
                .filter(ManualChunk.machine_id == machine_id)
                .all()
            )
        if not rows:
            return f"No manual content found for machine '{machine_id}'."

        query_lower = query.lower()
        scored = []
        for r in rows:
            score = sum(1 for word in query_lower.split() if word in r.chunk_text.lower())
            scored.append((score, r.chunk_text))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = [text for _, text in scored[:3] if scored[0][0] > 0]
        if not top:
            return f"No relevant manual sections found for query '{query}' on machine '{machine_id}'."
        return "\n\n".join(top)
    except Exception as exc:
        logger.error("search_manual error: %s", exc)
        return f"Error searching manual: {exc}"


@tool
def check_spare_parts(machine_id: str) -> str:
    """Check available spare parts inventory for a given machine_id."""
    try:
        with Session(engine) as session:
            rows = (
                session.query(SparePart)
                .filter(SparePart.machine_id == machine_id)
                .all()
            )
        if not rows:
            return f"No spare parts on record for machine '{machine_id}'."
        lines = [
            f"{r.part_name} (PN: {r.part_number}) – qty: {r.quantity_available}"
            for r in rows
        ]
        return "\n".join(lines)
    except Exception as exc:
        logger.error("check_spare_parts error: %s", exc)
        return f"Error checking spare parts: {exc}"


@tool
def create_maintenance_ticket(machine_id: str, error_code: str, description: str) -> str:
    """Create a maintenance ticket for a machine failure. Prevents duplicate open tickets."""
    try:
        with Session(engine) as session:
            existing = (
                session.query(MaintenanceTicket)
                .filter(
                    MaintenanceTicket.machine_id == machine_id,
                    MaintenanceTicket.error_code == error_code,
                    MaintenanceTicket.status == "open",
                )
                .first()
            )
            if existing:
                return (
                    f"Duplicate ticket prevented: an open ticket already exists for "
                    f"machine '{machine_id}' / error '{error_code}' (ticket id={existing.id})."
                )
            ticket = MaintenanceTicket(
                machine_id=machine_id,
                error_code=error_code,
                description=description,
                status="open",
                created_at=datetime.utcnow(),
            )
            session.add(ticket)
            session.commit()
            session.refresh(ticket)
            return (
                f"Maintenance ticket created: id={ticket.id}, machine='{machine_id}', "
                f"error='{error_code}', status='open'."
            )
    except Exception as exc:
        logger.error("create_maintenance_ticket error: %s", exc)
        return f"Error creating maintenance ticket: {exc}"


TOOLS = [
    get_maintenance_history,
    search_manual,
    check_spare_parts,
    create_maintenance_ticket,
]
