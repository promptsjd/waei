"""Explicit compatibility rules shared by schema validation and prompt export."""

CURRENT_VERSION = "2.0"
SUPPORTED_VERSIONS = frozenset({"1.0", CURRENT_VERSION})


def policy_for(analysis):
    return analysis if analysis["version"] == CURRENT_VERSION else analysis["brief"]


def schema_for(version, filename):
    if version == "1.0" and filename in {"input.schema.json", "edit-plan.schema.json"}:
        return filename.replace(".schema.json", "-v1.schema.json")
    return filename
