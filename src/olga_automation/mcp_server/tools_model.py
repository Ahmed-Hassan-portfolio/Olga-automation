"""Model inspection tools: read_case_summary, get_parameter, list_keywords, get_output_config.

All tools use async timeout wrappers (30s) and response truncation to prevent
stdio pipe buffer deadlocks. See docs/MCP_STDIO_STALLING_FIX.md.
"""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import anyio
from mcp.server.fastmcp import Context
from pydantic import Field

logger = logging.getLogger("olga-automation.tools.model")

# Maximum response size in bytes before truncation kicks in.
# Windows stdio pipe buffers are typically 4-8KB; stay well under.
_MAX_RESPONSE_BYTES = 4096


def register_model_tools(mcp):
    """Register model inspection tools on the MCP server."""

    @mcp.tool()
    async def read_case_summary(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to inspect")
        ],
        ctx: Context = None,
    ) -> str:
        """Parse an OLGA .opi model file and return a structured summary.

        Returns a comprehensive summary including flowpaths, nodes, valves, sources,
        output configurations, integration settings, and connections.
        """
        def _sync():
            from olga_automation.mcp_server.serialization import serialize_result
            from olga_automation.opi_parser.reader import get_model_summary

            summary = get_model_summary(Path(opi_path))
            logger.info(f"read_case_summary: {opi_path}")
            serialized = serialize_result(summary)

            # Truncate large responses to prevent stdio pipe buffer deadlock
            if len(serialized) > _MAX_RESPONSE_BYTES:
                data = json.loads(serialized)
                # Strip detailed key data from flowpaths, keep counts only
                for fp_key in ("flowpaths",):
                    if fp_key in data and isinstance(data[fp_key], list):
                        for fp in data[fp_key]:
                            if "keywords" in fp and isinstance(fp["keywords"], list):
                                fp["keyword_count"] = len(fp["keywords"])
                                fp["keywords"] = [
                                    {"tag": kw.get("tag"), "type": kw.get("keyword_type")}
                                    for kw in fp["keywords"]
                                ]
                data["truncated"] = True
                data["hint"] = (
                    "Keyword details stripped to prevent stalling. "
                    "Use get_parameter or list_keywords with keyword_type filter for details."
                )
                return json.dumps(data, indent=2)

            return serialized

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
                "hint": "The model may be very large. Try get_parameter for specific values.",
            })
        except Exception as e:
            logger.exception(f"read_case_summary failed: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_parameter(
        opi_path: Annotated[str, Field(description="Absolute path to the .opi file")],
        tag: Annotated[
            str,
            Field(
                description="Keyword tag, e.g. 'OPTIONS_0' or 'FLOWPATH_7.VALVE_15'"
            ),
        ],
        key_name: Annotated[
            str, Field(description="Key name, e.g. 'MASSFLOW', 'ENDTIME'")
        ],
        ctx: Context = None,
    ) -> str:
        """Read a specific parameter value from a keyword in the .opi file.

        Returns the key's value(s), unit, and data type. Raises an error if the
        keyword tag is not found.
        """
        def _sync():
            from olga_automation.exceptions import KeywordNotFoundError
            from olga_automation.mcp_server.serialization import serialize_result
            from olga_automation.opi_parser.reader import get_parameter as _get_parameter

            result = _get_parameter(Path(opi_path), tag, key_name)

            if result is None:
                error_msg = f"Key '{key_name}' not found on keyword '{tag}'"
                logger.warning(error_msg)
                return json.dumps({"error": error_msg})

            logger.info(f"get_parameter: {tag}.{key_name}")
            return serialize_result(result)

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
                "hint": "The model may be very large.",
            })
        except Exception as e:
            if "KeywordNotFoundError" in type(e).__name__ or "not found" in str(e).lower():
                logger.warning(f"get_parameter: keyword not found - {e}")
            else:
                logger.exception(f"get_parameter failed: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def list_keywords(
        opi_path: Annotated[str, Field(description="Absolute path to the .opi file")],
        keyword_type: Annotated[
            str | None,
            Field(
                description="Filter by keyword type, e.g. 'PIPE', 'VALVE', 'SOURCE'. Omit to list all keywords."
            ),
        ] = None,
        include_ncs: Annotated[
            bool,
            Field(
                description="Include network components (NODE, FLOWPATH, ANNULUS) in results. Default true."
            ),
        ] = True,
        ctx: Context = None,
    ) -> str:
        """List all keywords in the .opi file, optionally filtered by type.

        Returns keyword tags, types, and their key counts.
        """
        def _sync():
            from olga_automation.mcp_server.serialization import serialize_result
            from olga_automation.opi_parser.reader import list_keywords as _list_keywords

            keywords = _list_keywords(Path(opi_path), keyword_type, include_ncs=include_ncs)
            logger.info(
                f"list_keywords: {opi_path}, type={keyword_type}, count={len(keywords)}"
            )

            # Serialize first, then check size
            serialized = serialize_result(keywords)

            # Truncate if response is too large AND no type filter is applied
            if len(serialized) > _MAX_RESPONSE_BYTES and keyword_type is None:
                # Build slim list: tag + type + key count only (no full key data)
                slim = []
                for kw in keywords:
                    if hasattr(kw, "__dataclass_fields__"):
                        d = asdict(kw)
                    else:
                        d = kw
                    slim.append({
                        "tag": d.get("tag"),
                        "keyword_type": d.get("keyword_type"),
                        "key_count": len(d.get("keys", {})),
                    })
                return json.dumps({
                    "keywords": slim,
                    "truncated": True,
                    "total_count": len(keywords),
                    "hint": (
                        "Response truncated to prevent stalling. "
                        "Use keyword_type filter (e.g. keyword_type='VALVE') "
                        "to get full key data for specific types."
                    ),
                }, indent=2)

            return serialized

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
                "hint": "Use keyword_type filter to narrow the query.",
            })
        except Exception as e:
            logger.exception(f"list_keywords failed: {e}")
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_output_config(
        opi_path: Annotated[str, Field(description="Absolute path to the .opi file")],
        ctx: Context = None,
    ) -> str:
        """Get the current output configuration from the .opi file.

        Shows TREND, PROFILE, TRENDDATA, and PROFILEDATA settings - what variables
        OLGA will record during simulation.
        """
        def _sync():
            from olga_automation.opi_parser.reader import get_output_configuration

            result = get_output_configuration(Path(opi_path))
            logger.info(f"get_output_config: {opi_path}")
            return json.dumps(result, indent=2)

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
            })
        except Exception as e:
            logger.exception(f"get_output_config failed: {e}")
            return json.dumps({"error": str(e)})
