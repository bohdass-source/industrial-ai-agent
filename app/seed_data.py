"""Генерация synthetic data + мануалов. Запуск: python -m app.seed_data [--if-empty]."""

import argparse
import random
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, Machine, MaintenanceHistory, SparePart
from app.seed_catalogs import ERROR_CATALOG, EXTRA_PARTS, TECHNICIANS

random.seed(2026)

MANUALS_DIR = Path(__file__).resolve().parent / "data" / "manuals"

MACHINE_LINES = [
    ("Conveyor Line", "Shop A", 12, "conveyor"),
    ("Packaging Machine", "Shop B", 10, "packaging"),
    ("CNC Mill", "Shop C", 8, "cnc"),
    ("Air Compressor", "Utility", 6, "compressor"),
    ("Cooling Pump", "Utility", 8, "pump"),
    ("Robot Arm", "Shop B", 6, "robot"),
]


def family_of(name: str) -> str:
    for prefix, _, _, fam in MACHINE_LINES:
        if name.startswith(prefix):
            return fam
    return "conveyor"


def generate_machines() -> list[Machine]:
    machines = []
    for prefix, location, n, _ in MACHINE_LINES:
        for i in range(1, n + 1):
            machines.append(Machine(
                machine_name=f"{prefix} {i}",
                location=location,
                status="stopped" if (prefix == "Conveyor Line" and i == 4) else random.choices(
                    ["running", "maintenance", "degraded", "stopped"],
                    weights=[72, 14, 10, 4],
                )[0],
                last_service=datetime.now() - timedelta(days=random.randint(5, 400)),
            ))
    return machines


def generate_history(machines: list[Machine]) -> list[MaintenanceHistory]:
    rows = []
    c4 = next(m for m in machines if m.machine_name == "Conveyor Line 4")
    demo = [
        (122, "E142: остановка привода, перегрузка", "Замена ремня BLT-142, регулировка натяжения", "Иванов И.И."),
        (48, "E142: остановка привода, перегрузка", "Очистка датчика SNS-101, сброс ошибки", "Петров П.П."),
        (14, "E142: остановка привода, перегрузка", "Замена ремня BLT-142 и подшипника BRG-1030", "Сидоров С.С."),
    ]
    for days, problem, repair, tech in demo:
        rows.append(MaintenanceHistory(
            machine_id=c4.machine_id,
            problem=problem,
            repair=repair,
            technician=tech,
            date=datetime.now() - timedelta(days=days),
        ))

    for _ in range(350 - len(rows)):
        m = random.choice(machines)
        err = random.choice(ERROR_CATALOG[family_of(m.machine_name)])
        cause = random.choice(err["causes"])
        part = err["parts"][0][0] if err["parts"] else "—"
        rows.append(MaintenanceHistory(
            machine_id=m.machine_id,
            problem=f"{err['code']}: {err['title'].lower()}, {cause.lower()}",
            repair=random.choice([
                f"Замена {part}, проверка параметров",
                "Регулировка и сброс ошибки",
                f"Замена {part}, смазка узлов",
            ]),
            date=datetime.now() - timedelta(days=random.randint(1, 1095), hours=random.randint(0, 23)),
            technician=random.choice(TECHNICIANS),
        ))
    return rows


def generate_parts() -> list[SparePart]:
    parts: dict[str, SparePart] = {}
    for errors in ERROR_CATALOG.values():
        for err in errors:
            for pn, pname, _ in err["parts"]:
                parts.setdefault(pn, SparePart(
                    part_number=pn,
                    name=pname,
                    quantity=0 if pn == "BLT-142" else random.randint(0, 25),
                    location=random.choice(["Warehouse A3", "Shop A shelf 4", "Shop B shelf 2", "Utility store"]),
                ))
    for pn, pname in EXTRA_PARTS:
        parts.setdefault(pn, SparePart(
            part_number=pn,
            name=pname,
            quantity=random.randint(5, 60),
            location="Warehouse A3",
        ))
    return list(parts.values())


def generate_manuals() -> None:
    """Из каталога ошибок генерируем markdown-мануалы app/data/manuals/{code}.md."""
    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    for errors in ERROR_CATALOG.values():
        for err in errors:
            parts_lines = "\n".join(f"| {pn} | {pname} | {q} |" for pn, pname, q in err["parts"])
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(err["steps"], 1))
            causes = "\n".join(f"{i}. {c}" for i, c in enumerate(err["causes"], 1))
            doc = f"""# {err['code']} — {err['title']}

**Система:** {err['system']}
**Severity:** {err['severity']}

## Описание
{err['description']}

## Вероятные причины
{causes}

## Troubleshooting procedure
{steps}

## Требуемые запчасти
| Part Number | Наименование | Кол-во |
|-------------|--------------|--------|
{parts_lines}

## Safety
- Работы только после LOTO (отключение и блокировка питания).
- Повторный запуск после двух аварий подряд — только с инженером.
"""
            (MANUALS_DIR / f"{err['code']}.md").write_text(doc, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed synthetic data")
    parser.add_argument(
        "--if-empty",
        action="store_true",
        help="Пропустить, если данные уже есть (идемпотентный запуск)",
    )
    args = parser.parse_args()

    if args.if_empty:
        with SessionLocal() as s:
            if s.scalar(select(Machine).limit(1)) is not None:
                print("Data already present, skipping seed")
                return

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        machines = generate_machines()
        s.add_all(machines)
        s.flush()
        s.add_all(generate_history(machines))
        s.add_all(generate_parts())
        s.commit()
    generate_manuals()
    n_manuals = len(list(MANUALS_DIR.glob("*.md")))
    print(f"OK: machines=50, history=350, spare_parts={len(generate_parts())}, manuals={n_manuals}")


if __name__ == "__main__":
    main()
