"""Real autosave, append, cached analysis and export checks on an isolated server."""

import hashlib
import json
from editor_smoke_test import ROOT, OUTPUT_ROOT, checked, wait_for
import requests
from editor_smoke_test import URL


def upload(identifier, name):
    with (ROOT / "samples" / name).open("rb") as handle:
        return checked("POST", f"/api/editor/projects/{identifier}/clips",
                       files=[("videos", (name, handle, "video/mp4"))]).json()


def analyze(identifier):
    checked("POST", f"/api/editor/projects/{identifier}/analyze")
    return wait_for(identifier, "analyzed")


def generate(identifier, state):
    plan = {"version": "2.0", "input_id": state["analysis"]["input_id"],
            "sequence": [{"unit_ids": [unit["id"] for unit in state["analysis"]["units"]]}], "removed_unit_ids": []}
    checked("POST", f"/api/editor/projects/{identifier}/plan", json=plan)
    checked("POST", f"/api/editor/projects/{identifier}/render")
    return wait_for(identifier, "completed"), plan


def main():
    state = checked("POST", "/api/editor/workspace", data={"workspace": json.dumps({
        "topic": "Recording advice", "context": "Clear audio", "describe_visuals": False, "language": "en",
    })}).json()
    identifier = state["id"]
    assert state["name"] == "Project_1" and not state["assets"]
    rejected = requests.patch(URL + f"/api/editor/projects/{identifier}/workspace", json={"name": "Renamed"}, timeout=30)
    assert rejected.status_code == 400
    assert checked("GET", f"/api/editor/projects/{identifier}").json()["name"] == "Project_1"
    state = upload(identifier, "speech-demo.mp4")
    first_id = state["assets"][0]["id"]
    assert not state["has_analysis"]
    original = analyze(identifier)
    assert original["analysis_current"]
    original_prompt = checked("GET", f"/api/editor/projects/{identifier}/prompt").text
    folder = OUTPUT_ROOT / "editor" / identifier
    first_cache = next((folder / ".clip-analysis").glob("*.json"))
    cache_time = first_cache.stat().st_mtime_ns
    original_video, old_plan = generate(identifier, original)
    first_output = folder / original_video["video"]["file"]
    old_video_hash = hashlib.sha256(checked("GET", f"/api/editor/projects/{identifier}/video").content).hexdigest()
    state = upload(identifier, "speech-demo-second.mp4")
    assert len(state["assets"]) == 2 and not state["analysis_current"] and state["video"]["previous"]
    assert requests.get(URL + f"/api/editor/projects/{identifier}/prompt", timeout=30).status_code == 409
    restored = checked("PATCH", f"/api/editor/projects/{identifier}/workspace", json={"asset_ids": [first_id]}).json()
    assert restored["analysis_current"] and restored["ai_response_current"]
    assert checked("GET", f"/api/editor/projects/{identifier}/prompt").text == original_prompt
    upload(identifier, "speech-demo-second.mp4")
    updated = analyze(identifier)
    assert updated["analysis_current"] and len(updated["assets"]) == 2
    assert updated["analysis"]["input_id"] != original["analysis"]["input_id"]
    assert not updated["ai_response_current"] and not updated["plan_current"]
    assert first_cache.stat().st_mtime_ns == cache_time
    assert hashlib.sha256(checked("GET", f"/api/editor/projects/{identifier}/video").content).hexdigest() == old_video_hash
    rejected = requests.post(URL + f"/api/editor/projects/{identifier}/plan", json=old_plan, timeout=30)
    assert rejected.status_code == 400
    caches = {path.name: path.stat().st_mtime_ns for path in (folder / ".clip-analysis").glob("*.json")}
    checked("PATCH", f"/api/editor/projects/{identifier}/workspace", json={"context": "Additional context"})
    latest = analyze(identifier)
    assert caches == {path.name: path.stat().st_mtime_ns for path in (folder / ".clip-analysis").glob("*.json")}
    final, _ = generate(identifier, latest)
    assert first_output.is_file() and final["video"]["file"] != original_video["video"]["file"]
    assert not final["video"]["previous"] and final["ai_response_current"]
    report = {"passed": True, "project_id": identifier, "clips": len(final["assets"]),
              "old_clip_cache_reused": True, "previous_export_preserved": True}
    (OUTPUT_ROOT / "workspace-test-results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("PASS: workspace autosave, reopen, appended clips, cached analysis, stale-response guard and preserved exports", flush=True)


if __name__ == "__main__":
    main()
