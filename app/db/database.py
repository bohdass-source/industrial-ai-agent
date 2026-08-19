import logging
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.config import settings

logger = logging.getLogger(__name__)
engine = create_engine(settings.database_url, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass


class MaintenanceHistory(Base):
    __tablename__ = "maintenance_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(String(64), nullable=False, index=True)
    error_code = Column(String(64), nullable=True)
    description = Column(Text, nullable=False)
    resolution = Column(Text, nullable=True)
    technician = Column(String(128), nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(String(64), nullable=False, index=True)
    part_number = Column(String(64), nullable=False)
    part_name = Column(String(256), nullable=False)
    quantity_available = Column(Integer, default=0, nullable=False)


class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(String(64), nullable=False, index=True)
    error_code = Column(String(64), nullable=True)
    description = Column(Text, nullable=False)
    status = Column(String(32), default="open", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class ManualChunk(Base):
    """Stores text chunks from maintenance manuals for RAG retrieval."""

    __tablename__ = "manual_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    machine_id = Column(String(64), nullable=False, index=True)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Text, nullable=True)  # JSON-encoded vector when pgvector unavailable


def init_db() -> None:
    with engine.connect() as conn:
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
            logger.info("pgvector extension enabled.")
        except Exception as exc:
            logger.warning("pgvector extension not available: %s", exc)
            conn.rollback()

    Base.metadata.create_all(engine)

    _seed_demo_data()


def _seed_demo_data() -> None:
    with Session(engine) as session:
        if session.query(MaintenanceHistory).count() > 0:
            return

        history_rows = [
            MaintenanceHistory(
                machine_id="CNC-001",
                error_code="E404",
                description="Spindle motor overheated due to blocked cooling vent.",
                resolution="Cleaned cooling vent and replaced thermal paste.",
                technician="Alice",
            ),
            MaintenanceHistory(
                machine_id="CNC-001",
                error_code="E101",
                description="Axis encoder signal lost during machining cycle.",
                resolution="Replaced encoder cable and recalibrated.",
                technician="Bob",
            ),
            MaintenanceHistory(
                machine_id="ROBOT-002",
                error_code="E200",
                description="Joint 3 torque limit exceeded during pick-and-place.",
                resolution="Reduced acceleration profile and lubricated joint.",
                technician="Alice",
            ),
        ]
        session.add_all(history_rows)

        parts = [
            SparePart(machine_id="CNC-001", part_number="SP-COOL-01", part_name="Cooling Fan Assembly", quantity_available=3),
            SparePart(machine_id="CNC-001", part_number="SP-ENC-01", part_name="Axis Encoder", quantity_available=5),
            SparePart(machine_id="ROBOT-002", part_number="SP-BEAR-J3", part_name="Joint 3 Bearing", quantity_available=2),
        ]
        session.add_all(parts)

        chunks = [
            ManualChunk(
                machine_id="CNC-001",
                chunk_text=(
                    "CNC-001 Spindle Motor Overheating (E404): "
                    "Inspect cooling vent for blockages. Clean with compressed air. "
                    "Check thermal paste on heat sink. Replace if degraded. "
                    "Verify coolant pump operation."
                ),
            ),
            ManualChunk(
                machine_id="CNC-001",
                chunk_text=(
                    "CNC-001 Encoder Fault (E101): "
                    "Check encoder cable for damage or loose connector. "
                    "Verify shield grounding. Replace cable if signal noise is detected. "
                    "Recalibrate axis after replacement."
                ),
            ),
            ManualChunk(
                machine_id="ROBOT-002",
                chunk_text=(
                    "ROBOT-002 Joint Torque Limit (E200): "
                    "Reduce programmed acceleration profile. "
                    "Inspect joint for mechanical binding. Apply recommended lubricant. "
                    "Verify payload is within rated capacity."
                ),
            ),
        ]
        session.add_all(chunks)

        session.commit()
        logger.info("Demo data seeded.")
