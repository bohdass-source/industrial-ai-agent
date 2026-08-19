import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.db.database import init_db
from app.api.routes import router

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up – initialising database schema …")
    try:
        init_db()
        logger.info("Database ready.")
    except Exception as exc:
        logger.error("Database initialisation failed: %s", exc)
    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="Industrial AI Agent",
    description=(
        "Production-oriented Industrial AI maintenance agent. "
        "Diagnoses machine failures, retrieves maintenance history and manuals, "
        "checks spare parts, generates repair recommendations, and creates tickets."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please try again later."},
    )
