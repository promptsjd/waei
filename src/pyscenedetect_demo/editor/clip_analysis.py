"""Reusable analysis of one immutable source clip."""

import hashlib
import json
from dataclasses import asdict

from pyscenedetect_demo.media import probe, run_command, file_hash
from pyscenedetect_demo.scene_context import analyze_scene_context
from pyscenedetect_demo.storage import ProjectRepository, read_json, write_json
from pyscenedetect_demo.transcription import WordTranscriber, has_audible_signal
from .segmentation import SEGMENTATION_VERSION, build_units


def cache_path(folder, asset, options, settings):
    key = {"version": SEGMENTATION_VERSION, "sha256": asset["sha256"], "language": options.get("language") or "",
           "describe_visuals": options.get("describe_visuals", True),
           "models": asdict(settings.models), "detection": asdict(settings.detection),
           "segmentation": asdict(settings.segmentation)}
    key["segmentation"]["fillers"] = sorted(key["segmentation"]["fillers"])
    digest = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()
    return folder / ".clip-analysis" / f"{digest}.json"


def seed_saved_analysis(folder, state, settings):
    """Reuse saved transcription, rebuilding old fragments with current boundaries."""
    repository = ProjectRepository(folder)
    if not repository.artifact_path("analysis.json").is_file():
        return
    analysis = repository.read_artifact("analysis.json")
    mapping = repository.read_artifact("private-source-map.json")
    options = state.get("analysis_options") or state
    words = repository.read_artifact("words.json") if repository.artifact_path("words.json").is_file() else {}
    library = {**state.get("asset_library", {}), **{asset["id"]: asset for asset in state.get("assets", [])}}
    for asset_id, details in mapping["assets"].items():
        asset = library.get(asset_id)
        if not asset or not asset.get("sha256"):
            continue
        path = cache_path(folder, asset, options, settings)
        if path.exists():
            continue
        units = []
        for unit in analysis["units"]:
            source = mapping["units"][unit["id"]]
            if source["asset_id"] == asset_id:
                units.append({**unit, "start_ms": source["in_ms"], "end_ms": source["out_ms"]})
        if units:
            record = words.get(asset_id, {"language": None, "words": []})
            if record.get("words"):
                old_units = units
                units = build_units(record["words"], details["duration_ms"], policy=settings.segmentation)
                for unit in units:
                    context = max(old_units, key=lambda old: max(0, min(unit["end_ms"], old["end_ms"])
                                  - max(unit["start_ms"], old["start_ms"])))
                    unit["visual_description"] = context.get("visual_description")
            elif any(unit["kind"] == "speech" for unit in units):
                # Without word timing, old sentence fragments cannot be safely
                # regrouped. Analyze this source instead of blessing old cuts.
                continue
            write_json(path, {"details": {**asset, **details}, "units": units,
                              "words": record,
                              "complete": analysis["analysis_complete"]})


def analyze_clip(folder, asset, state, settings, models, progress):
    source = folder / "media" / f"{asset['id']}.mp4"
    if file_hash(source) != asset["sha256"]:
        raise ValueError("A stored clip has changed. Upload the original clip again.")
    cached = cache_path(folder, asset, state, settings)
    if cached.is_file():
        try:
            result = read_json(cached)
            if all(key in result for key in ("details", "units", "words", "complete")):
                return result
        except (OSError, ValueError):
            pass
    details = probe(source)
    progress("detecting_scenes", 0, 1)
    scenes = analyze_scene_context(source, folder / "scene_analysis" / asset["id"], settings=settings,
                                   describe_visuals=state["describe_visuals"], progress_callback=progress)
    words, language, audible = [], None, False
    if details["has_audio"]:
        progress("transcribing_words", 0, 1)
        audio = folder / "media" / f"{asset['id']}.wav"
        run_command(["ffmpeg", "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                     "-af", "aresample=async=1:first_pts=0", "-c:a", "pcm_s16le", str(audio)])
        if "speech" not in models:
            models["speech"] = WordTranscriber(settings)
        words, language = models["speech"].transcribe(audio, state.get("language") or None)
        audible = has_audible_signal(audio, settings.segmentation.audible_amplitude)
    unknown = audible and not words
    units = build_units(words, details["duration_ms"], unknown_speech=unknown, policy=settings.segmentation)
    for unit in units:
        scene = max(scenes, key=lambda row: max(0, min(unit["end_ms"], row["end_seconds"] * 1000)
                    - max(unit["start_ms"], row["start_seconds"] * 1000)), default={})
        unit["visual_description"] = scene.get("visual_description") or None
    result = {"details": details, "units": units, "words": {"language": language, "words": words}, "complete": not unknown}
    write_json(cached, result)
    return result
