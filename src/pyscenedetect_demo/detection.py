"""Scene boundaries shared by all workflows, without export side effects."""

from __future__ import annotations

import math
from pathlib import Path


def validate_video(video_path: Path, threshold: float, min_scene_len_seconds: float):
    if not video_path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not video_path.is_file():
        raise ValueError(f"Video path is not a file: {video_path}")
    if video_path.suffix.lower() != ".mp4":
        raise ValueError("Only MP4 input is supported in the current stage.")
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("Threshold must be finite and greater than 0.")
    if not math.isfinite(min_scene_len_seconds) or min_scene_len_seconds <= 0:
        raise ValueError("Minimum scene length must be finite and greater than 0 seconds.")


def build_detector(
    *, detector_name, threshold, min_scene_len_frames, content_detector_cls, adaptive_detector_cls
):
    if detector_name == "content":
        return content_detector_cls(threshold=threshold, min_scene_len=min_scene_len_frames)
    if detector_name == "adaptive":
        return adaptive_detector_cls(adaptive_threshold=threshold, min_scene_len=min_scene_len_frames)
    raise ValueError(f"Unsupported detector: {detector_name}")


def choose_representative_frame(*, start_frame, end_frame, frame_mode):
    if frame_mode != "middle":
        raise ValueError(f"Unsupported frame mode: {frame_mode}")
    last_inclusive_frame = max(start_frame, end_frame - 1)
    return start_frame + ((last_inclusive_frame - start_frame) // 2)


def detect_boundaries(
    *,
    video_path,
    detector_name,
    threshold,
    min_scene_len_seconds,
    show_progress=False,
    progress_callback=None,
):
    validate_video(video_path, threshold, min_scene_len_seconds)
    try:
        from scenedetect import AdaptiveDetector, ContentDetector, SceneManager, open_video
    except ImportError as exc:
        raise RuntimeError("PySceneDetect is not installed. Run `pip install -e .` first.") from exc
    video = open_video(str(video_path))
    fps = float(video.frame_rate)
    minimum = max(1, round(min_scene_len_seconds * fps))
    manager = SceneManager()
    manager.add_detector(
        build_detector(
            detector_name=detector_name,
            threshold=threshold,
            min_scene_len_frames=minimum,
            content_detector_cls=ContentDetector,
            adaptive_detector_cls=AdaptiveDetector,
        )
    )
    manager.detect_scenes(video=video, show_progress=show_progress)
    scenes = manager.get_scene_list(start_in_scene=True)
    if progress_callback:
        progress_callback("detecting", 1, 1, f"Found {len(scenes)} scenes")
    return video, fps, minimum, scenes
