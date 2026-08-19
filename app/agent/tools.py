"""Инструменты агента: документация (RAG), БД машин, склад запчастей, тикеты."""

import ast
import json
from datetime import datetime, timedelta
from typing import Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Machine, MaintenanceHistory, MaintenanceTicket, SparePart
from app.rag.retriever import search_manual_rag


def _find_machine(name: str) -> Machine | None:
    with SessionLocal() as s:
        return s.scalar(select(Machine).where(Machine.machine_name.ilike(f"%{name.strip()}%")))


class ManualSearchInput(BaseModel):
    query: str = Field(description="Что ищем: описание проблемы или шаги устранения")
    error_code: Optional[str] = Field(default=None, description="Код ошибки, например E142")


@tool("search_manual", args_schema=ManualSearchInput)
def search_manual(query: str, error_code: Optional[str] = None) -> str:
    """Ищет в технической документации (мануалах) описание ошибки
    и troubleshooting procedure. Агент сам решает, когда вызывать."""
    q = f"{error_code} {query}" if error_code else query
    return search_manual_rag(query=q, error_code=error_code, k=settings.rag_k)


class MachineInput(BaseModel):
    machine_name: str = Field(description="Название машины, например 'Conveyor Line 4'")


@tool("get_machine_info", args_schema=MachineInput)
def get_machine_info(machine_name: str) -> str:
    """Статус, локация и дата последнего ТО машины."""
    m = _find_machine(machine_name)
    if not m:
        # Не подсказывать реальные имена машин: агент не должен подменять
        # запрошенную (несуществующую) машину одной из предложенных.
        return (
            f"Машина '{machine_name}' не найдена в системе. "
            "Не используй другую машину вместо неё — уточни точное название у оператора."
        )
    return (
        f"machine_id={m.machine_id} | {m.machine_name} | location={m.location} | "
        f"status={m.status} | last_service={m.last_service:%Y-%m-%d}"
    )


class HistoryInput(BaseModel):
    machine_name: str = Field(description="Название машины, например 'Conveyor Line 4'")
    months: int = Field(default=24, ge=1, le=60, description="За сколько месяцев смотреть")


@tool("get_machine_history", args_schema=HistoryInput)
def get_machine_history(machine_name: str, months: int = 24) -> str:
    """История ремонтов машины за последние N месяцев."""
    m = _find_machine(machine_name)
    if not m:
        return f"Машина '{machine_name}' не найдена."
    since = datetime.now() - timedelta(days=months * 30)
    with SessionLocal() as s:
        rows = s.execute(
            select(MaintenanceHistory)
            .where(
                MaintenanceHistory.machine_id == m.machine_id,
                MaintenanceHistory.date >= since,
            )
            .order_by(MaintenanceHistory.date.desc())
            .limit(10)
        ).scalars().all()
    if not rows:
        return f"За последние {months} мес ремонтов не зафиксировано."
    return "\n".join(
        f"- {r.date:%Y-%m-%d} | {r.problem} -> {r.repair} | {r.technician}" for r in rows
    )


class SparePartsInput(BaseModel):
    part_numbers: list[str] = Field(
        description=(
            'JSON-массив строк. Передавай именно массив, не строку. '
            'Пример: ["BLT-142", "RLC-142"]'
        )
    )

    @field_validator("part_numbers", mode="before")
    @classmethod
    def normalize_part_numbers(cls, value):
        if isinstance(value, str):
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, SyntaxError):
                pass
        return value


@tool("check_spare_parts", args_schema=SparePartsInput)
def check_spare_parts(part_numbers: list[str]) -> str:
    """Проверяет наличие запчастей на складе по парт-номерам."""
    if not part_numbers:
        return "Не указаны номера запчастей."
    lines = []
    with SessionLocal() as s:
        for pn in part_numbers:
            p = s.get(SparePart, pn)
            if p is None:
                lines.append(f"{pn}: номер не найден в справочнике")
            elif p.quantity <= 0:
                lines.append(f"{pn} ({p.name}): НЕТ НА СКЛАДЕ")
            else:
                lines.append(f"{pn} ({p.name}): {p.quantity} шт., склад: {p.location}")
    return "\n".join(lines)


class TicketInput(BaseModel):
    machine_name: str = Field(description="Название машины, например 'Conveyor Line 4'")
    error_code: Optional[str] = Field(default=None, description="Код ошибки, например E142")
    title: str = Field(description="Краткий заголовок заявки")
    description: str = Field(description="Детали: симптомы, найденные причины, шаги")
    priority: str = Field(default="medium", description="low | medium | high | critical")
    recommended_parts: Optional[str] = Field(
        default=None, description="Рекомендуемые запчасти, например 'BLT-142 (нет на складе)'"
    )


@tool("create_maintenance_ticket", args_schema=TicketInput)
def create_maintenance_ticket(
    machine_name: str,
    error_code: Optional[str],
    title: str,
    description: str,
    priority: str = "medium",
    recommended_parts: Optional[str] = None,
) -> str:
    """Создаёт maintenance ticket (заявку на ремонт) в системе."""
    m = _find_machine(machine_name)
    if m is None:
        # Бизнес-правило: заявка создаётся только для реально существующей машины.
        return json.dumps(
            {
                "ticket_id": None,
                "error": "machine_not_found",
                "message": f"Машина '{machine_name}' не найдена. Тикет не создан.",
            },
            ensure_ascii=False,
        )
    with SessionLocal() as s:
        ticket = MaintenanceTicket(
            machine_id=m.machine_id,
            error_code=error_code,
            title=title[:200],
            description=description,
            recommended_parts=recommended_parts,
            priority=priority,
            status="open",
        )
        s.add(ticket)
        s.commit()
        s.refresh(ticket)
        return json.dumps(
            {"ticket_id": ticket.ticket_id, "title": ticket.title,
             "priority": ticket.priority, "status": ticket.status},
            ensure_ascii=False,
        )
