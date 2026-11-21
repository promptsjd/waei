"""Identity of editable project content and its derived analysis."""

import hashlib
import json


DEFAULTS = {"topic": "", "context": "", "allow_reorder": False, "describe_visuals": True, "language": ""}
FIELDS = tuple(DEFAULTS)


def signature(state):
    content = {key: state.get(key, default) for key, default in DEFAULTS.items()}
    content["assets"] = [(asset["id"], asset.get("sha256", "")) for asset in state.get("assets", [])]
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def analysis_current(state, has_analysis):
    return has_analysis and (not state.get("analysis_signature") or state["analysis_signature"] == signature(state))


def preserve_baseline(repository, state):
    """Record a legacy project's content before its first workspace edit."""
    changes = {}
    if repository.artifact_path("analysis.json").is_file() and not state.get("analysis_signature"):
        changes["analysis_signature"] = signature(state)
        changes["analysis_options"] = {key: state.get(key) for key in ("language", "describe_visuals")}
    if state.get("output_file") and not state.get("last_video"):
        script = repository.read_artifact("resolved.json").get("script", "") if repository.artifact_path("resolved.json").is_file() else ""
        changes["last_video"] = {
            "file": state["output_file"], "plan_revision": state.get("plan_revision", ""),
            "input_id": state.get("input_id", ""), "signature": changes.get("analysis_signature", state.get("analysis_signature", signature(state))),
            "script": script,
        }
    return changes
