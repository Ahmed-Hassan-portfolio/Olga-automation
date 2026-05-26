"""Model modification tools: set_parameter, set_output_variables, create_variant, validate_model, add_keyword, remove_keyword."""

import json
import logging
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import Context
from pydantic import Field

logger = logging.getLogger("olga-automation.tools.modify")


def register_modify_tools(mcp):
    """Register 6 model modification tools.

    - set_parameter: Modify a single parameter value
    - set_output_variables: Configure trend/profile output variables
    - create_variant: Create a modified copy of a model
    - validate_model: Validate model using OLGA's validation
    - add_keyword: Add a new keyword or network component
    - remove_keyword: Remove a keyword or network component by tag
    """

    @mcp.tool()
    def set_parameter(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to modify")
        ],
        tag: Annotated[
            str,
            Field(
                description="Keyword tag, e.g. 'OPTIONS_0' or 'FLOWPATH_7.SOURCE_18'"
            ),
        ],
        key_name: Annotated[
            str, Field(description="Key name, e.g. 'MASSFLOW', 'ENDTIME'")
        ],
        new_values: Annotated[
            list[str],
            Field(description="New values to set, e.g. ['100'] or ['0.5', '1.0']"),
        ],
        unit: Annotated[
            str | None, Field(description="New unit (optional), e.g. 'kg/s', 'bara'")
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Modify a parameter value in an OLGA .opi model file.

        Changes are saved to disk immediately. Returns confirmation or an error message.

        Examples
        --------
        Set simulation end time:
        >>> set_parameter("model.opi", "OPTIONS_0", "ENDTIME", ["3600"], "s")

        Set source mass flow:
        >>> set_parameter("model.opi", "FLOWPATH_7.SOURCE_18", "MASSFLOW", ["100"], "kg/s")
        """
        try:
            from olga_automation.opi_parser.writer import (
                set_parameter as _set_parameter,
            )
            from olga_automation.exceptions import KeywordNotFoundError

            _set_parameter(Path(opi_path), tag, key_name, new_values, unit)

            return json.dumps(
                {
                    "status": "ok",
                    "message": f"Set {key_name} on {tag} to {new_values}",
                }
            )

        except KeywordNotFoundError as e:
            logger.warning(f"Keyword not found: {e}")
            return json.dumps({"error": f"Keyword not found: {e}"})
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in set_parameter: {e}")
            return json.dumps({"error": f"Failed to set parameter: {e}"})

    @mcp.tool()
    def set_output_variables(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to modify")
        ],
        trend_vars: Annotated[
            list[dict] | None,
            Field(
                description="Trend variables: list of {'variable': 'PT', 'position': 'WH'}. None = leave unchanged, [] = remove all."
            ),
        ] = None,
        profile_vars: Annotated[
            list[dict] | None,
            Field(
                description="Profile variables: list of {'variable': 'GT'}. None = leave unchanged, [] = remove all."
            ),
        ] = None,
        flowpath_tag: Annotated[
            str | None,
            Field(
                description="Target flowpath tag, e.g. 'FLOWPATH_7'. If omitted, targets the first flowpath."
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Configure what variables OLGA records during simulation.

        This is the key function for dynamic output configuration -- call it before each
        simulation to control what data is captured. Sets TRENDDATA and PROFILEDATA keywords.

        Examples
        --------
        Configure trend outputs at two positions:
        >>> set_output_variables(
        ...     "model.opi",
        ...     trend_vars=[
        ...         {"variable": "PT", "position": "WH"},
        ...         {"variable": "TM", "position": "WH"}
        ...     ]
        ... )

        Configure profile output for temperature:
        >>> set_output_variables("model.opi", profile_vars=[{"variable": "GT"}])

        Remove all output configuration:
        >>> set_output_variables("model.opi", trend_vars=[], profile_vars=[])
        """
        try:
            from olga_automation.opi_parser.output_config import (
                set_output_variables as _set_output_variables,
            )
            from olga_automation.exceptions import KeywordNotFoundError

            _set_output_variables(
                Path(opi_path),
                trend_vars=trend_vars,
                profile_vars=profile_vars,
                flowpath_tag=flowpath_tag,
            )

            trend_count = len(trend_vars) if trend_vars else 0
            profile_count = len(profile_vars) if profile_vars else 0

            return json.dumps(
                {
                    "status": "ok",
                    "message": f"Configured {trend_count} trend variable(s) and {profile_count} profile variable(s)",
                }
            )

        except KeywordNotFoundError as e:
            logger.warning(f"Keyword not found: {e}")
            return json.dumps({"error": f"Keyword not found: {e}"})
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in set_output_variables: {e}")
            return json.dumps({"error": f"Failed to set output variables: {e}"})

    @mcp.tool()
    def create_variant(
        base_opi: Annotated[str, Field(description="Absolute path to the base .opi file")],
        output_opi: Annotated[
            str, Field(description="Absolute path for the new variant file")
        ],
        modifications: Annotated[
            list[dict],
            Field(
                description="List of modifications: [{'tag': 'OPTIONS_0', 'key': 'STEADYSTATE', 'values': ['ON']}]"
            ),
        ],
        pvt_file: Annotated[
            str | None,
            Field(
                description="Path to PVT fluid property file (.tab). Required when "
                "the base model's PVT path won't resolve from the new variant "
                "location. The file will be copied next to the variant."
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Create a variant .opi file from a base model with parameter modifications.

        Copies the base file, then applies all modifications. The base file is never modified.
        If the PVT file referenced in the base model cannot be found from the new variant
        location, provide pvt_file to have it copied automatically.

        Examples
        --------
        Create a steady-state variant:
        >>> create_variant(
        ...     "base.opi",
        ...     "variant_steady.opi",
        ...     [{"tag": "OPTIONS_0", "key": "STEADYSTATE", "values": ["ON"]}]
        ... )

        Create a variant with multiple parameter changes:
        >>> create_variant(
        ...     "base.opi",
        ...     "variant_high_flow.opi",
        ...     [
        ...         {"tag": "FLOWPATH_7.SOURCE_18", "key": "MASSFLOW", "values": ["150"]},
        ...         {"tag": "OPTIONS_0", "key": "ENDTIME", "values": ["7200"]}
        ...     ]
        ... )

        Create a variant with an explicit PVT file:
        >>> create_variant(
        ...     "base.opi",
        ...     "runs/variant.opi",
        ...     [],
        ...     pvt_file="C:/Users/me/Documents/Multiflash/fluid.tab"
        ... )
        """
        try:
            from olga_automation.opi_parser.writer import (
                create_variant as _create_variant,
            )
            from olga_automation.exceptions import KeywordNotFoundError

            variant_path = _create_variant(
                Path(base_opi), Path(output_opi), modifications,
                pvt_file=pvt_file,
            )

            return json.dumps(
                {"status": "ok", "variant_path": str(variant_path)}
            )

        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except KeywordNotFoundError as e:
            logger.warning(f"Keyword not found: {e}")
            return json.dumps({"error": f"Keyword not found: {e}"})
        except ValueError as e:
            logger.warning(f"PVT file error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception(f"Error in create_variant: {e}")
            return json.dumps({"error": f"Failed to create variant: {e}"})

    @mcp.tool()
    def validate_model(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to validate")
        ],
        ctx: Context = None,
    ) -> str:
        """Validate an OLGA .opi model file using the 'opi -exitRC' command.

        Returns pass/fail status with any error or warning messages. Requires OLGA to be installed.

        Examples
        --------
        >>> validate_model("model.opi")
        {"valid": true, "errors": [], "warnings": []}
        """
        try:
            from olga_automation.opi_parser.validator import validate_opi
            from olga_automation.exceptions import OlgaExecutionError

            result = validate_opi(Path(opi_path))
            return json.dumps(result, indent=2)

        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except OlgaExecutionError as e:
            logger.warning(f"OLGA execution error: {e}")
            return json.dumps({"error": f"OLGA execution error: {e}"})
        except Exception as e:
            logger.exception(f"Error in validate_model: {e}")
            return json.dumps({"error": f"Failed to validate model: {e}"})

    @mcp.tool()
    def add_keyword(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to modify")
        ],
        keyword_type: Annotated[
            str,
            Field(
                description="Keyword type, e.g. 'SOURCE', 'VALVE', 'TRENDDATA', 'CONTROLLER'"
            ),
        ],
        keys: Annotated[
            dict | None,
            Field(
                description="Key-value data: {'MASSFLOW': {'values': ['50'], 'unit': 'kg/s'}}. None = use defaults only."
            ),
        ] = None,
        parent_tag: Annotated[
            str | None,
            Field(
                description="Parent scope: None=case-level, 'Library'=library, or NC tag like 'FLOWPATH_7'"
            ),
        ] = None,
        output_vars: Annotated[
            list[dict] | None,
            Field(
                description="For TRENDDATA/PROFILEDATA: [{'variable': 'PT', 'position': 'WH'}]"
            ),
        ] = None,
        nc_type: Annotated[
            str | None,
            Field(
                description="If provided, adds a network component instead of a keyword. Type: 'FLOWPATH', 'NODE', 'ANNULUS'"
            ),
        ] = None,
        nc_label: Annotated[
            str | None,
            Field(
                description="Label for the new NC (required when nc_type is provided)"
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Add a new keyword or network component to an OLGA .opi model file.

        If nc_type is provided, creates a new network component (NC) with optional
        initial keywords. Otherwise, adds a keyword at the specified scope.

        Examples
        --------
        Add a source keyword at case level:
        >>> add_keyword("model.opi", "SOURCE", {"MASSFLOW": {"values": ["50"], "unit": "kg/s"}})

        Add a valve under a flowpath:
        >>> add_keyword("model.opi", "VALVE", parent_tag="FLOWPATH_7")

        Add a new flowpath NC:
        >>> add_keyword("model.opi", "FLOWPATH", nc_type="FLOWPATH", nc_label="NewPipe")
        """
        try:
            from olga_automation.opi_parser.writer import (
                add_keyword as _add_keyword,
                add_network_component as _add_network_component,
            )
            from olga_automation.exceptions import KeywordNotFoundError

            # Validate keyword_type is non-empty when adding a keyword (not an NC)
            if nc_type is None and (not keyword_type or not keyword_type.strip()):
                return json.dumps(
                    {
                        "status": "error",
                        "message": "keyword_type must be a non-empty string",
                    }
                )

            if nc_type is not None:
                # Adding a network component
                initial_keywords = None
                if keyword_type:
                    initial_keywords = [
                        {
                            "keyword_type": keyword_type,
                            "keys": keys,
                            "output_vars": output_vars,
                        }
                    ]
                tag = _add_network_component(
                    Path(opi_path),
                    nc_type,
                    nc_label or nc_type,
                    initial_keywords=initial_keywords,
                )
                return json.dumps(
                    {
                        "status": "ok",
                        "tag": tag,
                        "message": f"Added {nc_type} with tag {tag}",
                    }
                )
            else:
                # Adding a keyword
                tag = _add_keyword(
                    Path(opi_path), keyword_type, keys, parent_tag, output_vars
                )
                return json.dumps(
                    {
                        "status": "ok",
                        "tag": tag,
                        "message": f"Added {keyword_type} with tag {tag}",
                    }
                )

        except KeywordNotFoundError as e:
            logger.warning(f"Keyword not found: {e}")
            return json.dumps({"error": f"Keyword not found: {e}"})
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in add_keyword: {e}")
            return json.dumps({"error": f"Failed to add keyword: {e}"})

    @mcp.tool()
    def remove_keyword(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to modify")
        ],
        tag: Annotated[
            str,
            Field(
                description="Tag of the keyword or NC to remove, e.g. 'SOURCE_5' or 'FLOWPATH_7'"
            ),
        ],
        is_nc: Annotated[
            bool,
            Field(
                description="Set to true if removing a network component (NC) instead of a keyword"
            ),
        ] = False,
        ctx: Context = None,
    ) -> str:
        """Remove a keyword or network component from an OLGA .opi model file.

        If is_nc is True, removes a network component and all its children.
        Otherwise, removes a keyword and auto-cleans any stale output references.

        Examples
        --------
        Remove a keyword:
        >>> remove_keyword("model.opi", "SOURCE_5")

        Remove a network component:
        >>> remove_keyword("model.opi", "FLOWPATH_7", is_nc=True)
        """
        try:
            from olga_automation.opi_parser.writer import (
                remove_keyword as _remove_keyword,
                remove_network_component as _remove_network_component,
            )

            if is_nc:
                success = _remove_network_component(Path(opi_path), tag)
            else:
                success = _remove_keyword(Path(opi_path), tag)

            if success:
                return json.dumps(
                    {
                        "status": "ok",
                        "message": f"Removed {'NC' if is_nc else 'keyword'} {tag}",
                    }
                )
            else:
                return json.dumps(
                    {
                        "status": "not_found",
                        "message": f"{'NC' if is_nc else 'Keyword'} '{tag}' not found",
                    }
                )

        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in remove_keyword: {e}")
            return json.dumps({"error": f"Failed to remove keyword: {e}"})
