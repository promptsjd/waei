"""Minimal scene context for editing; no reports or per-scene audio side effects."""

from __future__ import annotations

from .captions import normalize_caption
from .detection import detect_boundaries, choose_representative_frame
from .media import extract_frame
from .vision import describe_images_with_florence


def analyze_scene_context(
    video_path, output_root, *, settings, describe_visuals=False, progress_callback=None
):
    options = settings.detection
    _, fps, _, boundaries = detect_boundaries(
        video_path=video_path,
        detector_name=options.detector,
        threshold=options.threshold,
        min_scene_len_seconds=options.min_scene_len_seconds,
        progress_callback=progress_callback,
    )
    scenes = [
        {
            "start_seconds": round(start.get_seconds(), 3),
            "end_seconds": round(end.get_seconds(), 3),
            "visual_description": "",
        }
        for start, end in boundaries
    ]
    if describe_visuals:
        frames = output_root / video_path.stem / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        paths = []
        for index, (start, end) in enumerate(boundaries, 1):
            frame = choose_representative_frame(
                start_frame=int(start.get_frames()),
                end_frame=int(end.get_frames()),
                frame_mode=options.frame_mode,
            )
            path = frames / f"scene_{index:04d}.jpg"
            extract_frame(video_path=video_path, frame_number=frame, fps=fps, destination=path)
            paths.append(path)
            if progress_callback:
                progress_callback(
                    "exporting_frames", index, len(boundaries), f"Scene {index}/{len(boundaries)}"
                )
        captions = describe_images_with_florence(
            image_paths=paths,
            model_name=settings.models.vision_model,
            task_prompt=settings.models.caption_task,
            settings=settings,
            progress_callback=progress_callback,
        )
        for scene, text in zip(scenes, captions, strict=True):
            scene["visual_description"] = normalize_caption(text)
    return scenes
