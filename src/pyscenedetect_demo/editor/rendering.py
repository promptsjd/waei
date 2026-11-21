"""Validated source selection and media rendering, independent of HTTP."""

import math
import uuid
from pathlib import Path
from pyscenedetect_demo import contract
from pyscenedetect_demo.media import file_hash, probe, run_command
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.storage import project_state, update_project, ProjectRepository
from .workspace import signature


def render_project(folder, *, settings=None):
    settings = settings or AppSettings.from_env()
    profile = settings.render
    folder = Path(folder)
    state = project_state(folder)
    resolved = contract.resolve(
        ProjectRepository(folder).read_artifact("analysis.json"),
        ProjectRepository(folder).read_artifact("plan.json"),
        ProjectRepository(folder).read_artifact("private-source-map.json"),
    )
    if not resolved["timeline"]:
        raise ValueError("The plan retains no video. Paste a plan that retains at least one unit.")
    registry = {asset["id"]: asset for asset in state["assets"]}
    for asset_id in {item["asset_id"] for item in resolved["timeline"]}:
        path = folder / "media" / f"{asset_id}.mp4"
        if file_hash(path) != registry[asset_id]["sha256"]:
            raise ValueError("An uploaded source has changed. Create a new project before rendering.")
        actual = probe(path)
        if actual["duration_ms"] != registry[asset_id]["duration_ms"]:
            raise ValueError("Source duration changed after analysis.")
    first = registry[resolved["timeline"][0]["asset_id"]]
    ratio = min(1.0, profile.max_dimension / max(first["width"], first["height"]))
    width, height = (
        max(2, round(first["width"] * ratio / 2) * 2),
        max(2, round(first["height"] * ratio / 2) * 2),
    )
    render_dir = folder / "renders" / state["plan_revision"] / uuid.uuid4().hex
    render_dir.mkdir(parents=True, exist_ok=True)
    count = len(resolved["timeline"])
    for index, item in enumerate(resolved["timeline"]):
        update_project(
            folder, message=f"Rendering section {index + 1}/{count}", progress=round(90 * index / count)
        )
        asset = registry[item["asset_id"]]
        source = folder / "media" / f"{asset['id']}.mp4"
        # Use one common 30-fps duration for audio and video. The maximum
        # adjustment per range is one output frame.
        frame_count = max(1, math.floor((item["out_ms"] - item["in_ms"]) * profile.fps / 1000 + 1e-8))
        seconds = frame_count / profile.fps
        command = ["ffmpeg", "-y", "-v", "error", "-ss", f"{item['in_ms'] / 1000:.3f}", "-i", str(source)]
        if not asset["has_audio"]:
            command += ["-f", "lavfi", "-i", f"anullsrc=r={profile.audio_rate}:cl=stereo"]
        command += [
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if asset["has_audio"] else "1:a:0",
            "-t",
            f"{seconds:.9f}",
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={profile.fps},tpad=stop_mode=clone:stop_duration=0.1,setpts=PTS-STARTPTS",
            "-af",
            f"aresample={profile.audio_rate}:async=1:first_pts=0,apad,atrim=duration={seconds:.9f},asetpts=PTS-STARTPTS",
            "-c:v",
            profile.video_codec,
            "-preset",
            profile.preset,
            "-crf",
            str(profile.crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            "-ar",
            str(profile.audio_rate),
            "-ac",
            "2",
            str(render_dir / f"part_{index:05d}.mkv"),
        ]
        run_command(command)
    concat = render_dir / "parts.txt"
    concat.write_text("".join(f"file 'part_{index:05d}.mkv'\n" for index in range(count)), encoding="utf-8")
    output = render_dir / "edited.mp4"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(concat),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            profile.audio_bitrate,
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    actual = probe(output)
    tolerance = max(profile.minimum_tolerance_ms, profile.tolerance_per_range_ms * count)
    if abs(actual["duration_ms"] - resolved["duration_ms"]) > tolerance:
        raise ValueError("Rendered duration differs unexpectedly from the validated timeline.")
    update_project(
        folder,
        status="completed",
        message="Edited video ready. Play it to review the joins.",
        progress=100,
        output_file=str(output.relative_to(folder)),
        last_video={"file": str(output.relative_to(folder)), "plan_revision": state["plan_revision"],
                    "input_id": state.get("input_id", resolved.get("input_id", "")), "signature": signature(state),
                    "script": resolved["script"]},
        output_duration_ms=actual["duration_ms"],
        render_is_preview=resolved["status"] != "ready",
        error=None,
    )
