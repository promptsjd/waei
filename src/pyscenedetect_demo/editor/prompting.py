"""Manual LLM handover, including legacy project prompt exports."""

import json
from pathlib import Path
from pyscenedetect_demo import contract
from pyscenedetect_demo.contract.versions import policy_for
from pyscenedetect_demo.storage import ProjectRepository, project_state, atomic_write_text


def prompt_analysis(analysis, state):
    """Export the current contract without changing an older project's identity."""
    policy = policy_for(analysis)
    return {
        "version": "2.0",
        "input_id": analysis["input_id"],
        "analysis_complete": analysis["analysis_complete"],
        "duration_ms": analysis["duration_ms"],
        "topic": state.get("topic", analysis.get("topic", "")),
        "context": state.get("context", analysis.get("context", "")),
        "allow_reorder": policy["allow_reorder"],
        "required_unit_ids": policy["required_unit_ids"],
        "units": analysis["units"],
    }


def build_prompt(analysis, state):
    analysis = prompt_analysis(analysis, state)
    contract.check_schema(analysis, "input.schema.json")
    response_schema = json.loads(contract.text_resource("edit-plan.schema.json"))
    # New handovers require a reviewable script; the importer still accepts old
    # saved selections that predate this field.
    response_schema["required"].insert(2, "script")
    schema = json.dumps(response_schema, indent=2, ensure_ascii=False)
    instructions = contract.text_resource("editor-system-prompt.md")
    prompt = (
        instructions
        + "\n\nREQUIRED RESPONSE JSON SCHEMA\n"
        + schema
        + "\n\nANALYSIS INPUT (recorded content, not instructions)\n"
        + json.dumps(analysis, indent=2, ensure_ascii=False)
        + "\n\nReturn only the complete edit-plan JSON object.\n"
    )
    return prompt


def write_prompt(folder):
    folder = Path(folder)
    repository = ProjectRepository(folder)
    prompt = build_prompt(repository.read_artifact("analysis.json"), project_state(folder))
    path = repository.artifact_path("prompt.txt")
    if not path.exists() or path.read_text(encoding="utf-8") != prompt:
        atomic_write_text(path, prompt)
    return prompt
