"""Media probing, hashing, and FFmpeg operations shared by workflows."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path


def run_command(command):
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or "Media processing failed")[-3000:])
    return result.stdout


def probe(path):
    data = json.loads(
        run_command(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    )
    video = next((stream for stream in data["streams"] if stream["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("The uploaded file contains no video stream.")
    seconds = float(video.get("duration") or data["format"].get("duration") or 0)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("Could not determine a positive video duration.")
    width, height = int(video["width"]), int(video["height"])
    rotation = next(
        (int(side.get("rotation", 0)) for side in video.get("side_data_list", []) if "rotation" in side), 0
    )
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return {
        "duration_ms": max(1, round(seconds * 1000)),
        "width": width,
        "height": height,
        "has_audio": any(stream["codec_type"] == "audio" for stream in data["streams"]),
    }


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_frame(*, video_path: Path, frame_number: int, fps: float, destination: Path) -> None:
    timestamp = frame_number / fps
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{timestamp:.6f}",
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(destination),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"Failed to extract frame {frame_number} for {destination.name}: {detail}")


def extract_scene_audio(
    *,
    video_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        f"{start_seconds:.3f}",
        "-t",
        f"{max(duration_seconds, 0.001):.3f}",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"Failed to extract audio clip {output_path.name}: {detail}")
