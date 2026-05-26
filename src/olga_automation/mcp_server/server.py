"""OLGA Automation MCP Server - FastMCP entry point exposing 20 tools."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

# All logging to stderr + file, NEVER stdout (breaks stdio protocol)
LOG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(LOG_DIR / "server.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("olga-automation")

from mcp.server.fastmcp import Context, FastMCP


@dataclass
class AppContext:
    """Resources initialized at server startup, available to all tools."""

    config: any  # OlgaConfig
    base_models_dir: Path
    runs_dir: Path


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Initialize configuration at server startup."""
    logger.info("=== OLGA Automation Server Starting ===")

    # Import config loader
    from olga_automation.config import load_config

    config = load_config()

    # Ensure directories exist
    config.base_models_dir.mkdir(parents=True, exist_ok=True)
    config.runs_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Base models directory: {config.base_models_dir}")
    logger.info(f"Runs directory: {config.runs_dir}")

    logger.info("=== Server Ready ===")
    try:
        yield AppContext(
            config=config,
            base_models_dir=config.base_models_dir,
            runs_dir=config.runs_dir,
        )
    finally:
        logger.info("=== Server Shutting Down ===")


mcp = FastMCP("olga-automation", lifespan=app_lifespan)

# ---------------------------------------------------------------------------
# Register tools from submodules
# ---------------------------------------------------------------------------
from olga_automation.mcp_server.tools_batch import register_batch_tools
from olga_automation.mcp_server.tools_execution import register_execution_tools
from olga_automation.mcp_server.tools_model import register_model_tools
from olga_automation.mcp_server.tools_modify import register_modify_tools

register_model_tools(mcp)
register_modify_tools(mcp)
register_execution_tools(mcp)
register_batch_tools(mcp)

logger.info("Registered all tools on server 'olga-automation'")

if __name__ == "__main__":
    mcp.run(transport="stdio")
