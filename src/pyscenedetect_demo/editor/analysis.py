"""Compose one project analysis from cached and newly analyzed clips."""

import hashlib
import json
from pathlib import Path
from pyscenedetect_demo import contract
from pyscenedetect_demo.contract.versions import policy_for
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.storage import ProjectRepository, project_state, update_project
from .clip_analysis import analyze_clip, seed_saved_analysis
from .prompting import build_prompt
from .workspace import signature
from .segmentation import SEGMENTATION_VERSION


def analyze_project(folder, *, settings=None):
    settings = settings or AppSettings.from_env()
    folder = Path(folder)
    state = project_state(folder)
    content_signature = signature(state)
    repository = ProjectRepository(folder)
    required_ranges = set()
    if repository.artifact_path("analysis.json").is_file():
        previous = repository.read_artifact("analysis.json")
        previous_map = repository.read_artifact("private-source-map.json")["units"]
        required_ranges = {(previous_map[identifier]["asset_id"], previous_map[identifier]["in_ms"], previous_map[identifier]["out_ms"])
                           for identifier in policy_for(previous)["required_unit_ids"]}
    seed_saved_analysis(folder, state, settings)
    models = {}
    units, mappings, assets, word_records, updated_assets = [], {}, {}, {}, []
    virtual_cursor, complete, required = 0, True, []
    for index, asset in enumerate(state["assets"]):
        asset_id = asset["id"]

        def progress(stage, current, total, message=""):
            update_project(folder, message=f"Clip {index + 1}/{len(state['assets'])}: {stage.replace('_', ' ')} {message}",
                           progress=round(90 * index / len(state["assets"])))

        result = analyze_clip(folder, asset, state, settings, models, progress)
        details = result["details"]
        duration = details["duration_ms"]
        updated_assets.append({**asset, **details, "id": asset_id, "name": asset["name"]})
        complete = complete and result["complete"]
        word_records[asset_id] = result["words"]
        for unit in result["units"]:
            unit_id = f"u{len(units) + 1:05d}"
            units.append({**unit, "id": unit_id, "start_ms": virtual_cursor + unit["start_ms"],
                          "end_ms": virtual_cursor + unit["end_ms"]})
            mappings[unit_id] = {"asset_id": asset_id, "in_ms": unit["start_ms"], "out_ms": unit["end_ms"]}
            if any(source_id == asset_id and start < unit["end_ms"] and end > unit["start_ms"]
                   for source_id, start, end in required_ranges):
                required.append(unit_id)
        assets[asset_id] = {"duration_ms": duration}
        virtual_cursor += duration
    analysis = {"version": "2.0", "input_id": "", "analysis_complete": complete,
                "duration_ms": virtual_cursor, "topic": state.get("topic", ""), "context": state.get("context", ""),
                "allow_reorder": state["allow_reorder"], "required_unit_ids": required, "units": units}
    source_map = {"version": "2.0", "input_id": "", "assets": assets, "units": mappings}
    fingerprint = {"analysis": analysis, "source_map": source_map,
                   "media_hashes": [asset["sha256"] for asset in state["assets"]]}
    input_id = hashlib.sha256(json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    analysis["input_id"] = source_map["input_id"] = input_id
    contract.check_schema(analysis, "input.schema.json")
    prompt = build_prompt(analysis, state)
    with repository.locked():
        if signature(repository.state()) != content_signature:
            raise ValueError("Project changed during analysis. Analyze clips again.")
        repository.commit_analysis(analysis, source_map, word_records, prompt, updated_assets, content_signature,
                                   segmentation_version=SEGMENTATION_VERSION)
