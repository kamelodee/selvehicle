"""
Selvehicle — Entry point
Runs both the TCP server and the FastAPI HTTP server
concurrently in a single asyncio event loop.

Usage:
    python main.py

Environment variables:
    TCP_HOST          TCP bind address (default: 0.0.0.0)
    TCP_PORT          TCP port for terminal connections (default: 8808)
    HTTP_PORT         HTTP port for the admin API (default: 8000)
    DATABASE_URL      SQLAlchemy DB URL (default: sqlite:///./jt808.db)
                      Example for PostgreSQL:
                      postgresql://user:pass@localhost:5432/jt808
    IDLE_TIMEOUT_SECS Seconds before idle terminal connection is closed (default: 120)
    LOG_LEVEL         Logging level (default: INFO)
"""

import asyncio
import logging
import os

from dotenv import load_dotenv
load_dotenv()

import uvicorn

from jt808.server import run_tcp_server
from jt808.api import app
from jt808.models import create_tables

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8000"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_http_server():
    config = uvicorn.Config(
        app=app,
        host=HTTP_HOST,
        port=HTTP_PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    create_tables()
    logger.info("Starting Selvehicle Server")
    await asyncio.gather(
        run_tcp_server(),
        run_http_server(),
    )


if __name__ == "__main__":
    asyncio.run(main())
