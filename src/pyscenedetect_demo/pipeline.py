from __future__ import annotations

import csv
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pyscenedetect_demo.report import generate_html_report
from pyscenedetect_demo.vision import describe_images_with_florence
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.detection import detect_boundaries, choose_representative_frame as _choose_representative_frame
from pyscenedetect_demo.media import extract_frame as _extract_frame, extract_scene_audio as _run_ffmpeg_extract
from pyscenedetect_demo.captions import normalize_caption as _normalize_caption
from pyscenedetect_demo.transcription import transcribe_scenes
from pyscenedetect_demo.storage import write_json as _write_json


@dataclass(slots=True)
class SceneRecord:
    scene_id: int
    start_timecode: str
    end_timecode: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    start_frame: int
    end_frame: int
    representative_frame: int
    screenshot_path: str
    audio_path: str
    shot_size: str
    visual_description: str
    camera_motion: str
    dialogue: str
    sound_effects: str
    bgm: str
    transcript_language: str
    transcript_confidence: float | None
    notes: str


def run_scene_detection(
    *,
    video_path: Path,
    output_root: Path,
    detector_name: str,
    threshold: float,
    min_scene_len_seconds: float,
    frame_mode: str,
    transcribe: bool,
    asr_model_name: str,
    language: str | None,
    describe_visuals: bool,
    vision_model_name: str,
    show_progress: bool,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    settings = settings or AppSettings.from_env()
    video, fps, min_scene_len_frames, scene_list = detect_boundaries(
        video_path=video_path, detector_name=detector_name, threshold=threshold,
        min_scene_len_seconds=min_scene_len_seconds, show_progress=show_progress,
        progress_callback=progress_callback)

    video_output_dir = output_root / video_path.stem
    video_output_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = video_output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = video_output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    json_path = video_output_dir / "scenes.json"
    csv_path = video_output_dir / "scenes.csv"
    html_path = video_output_dir / "report.html"

    scene_records = _export_scene_frames(
        scene_list=scene_list,
        video_path=video_path,
        fps=fps,
        frames_dir=frames_dir,
        frame_mode=frame_mode,
        progress_callback=progress_callback,
    )
    _export_scene_audio(
        scene_records=scene_records,
        video_path=video_path,
        audio_dir=audio_dir,
        progress_callback=progress_callback,
    )
    if describe_visuals:
        _describe_scene_frames(
            scene_records=scene_records,
            frames_dir=frames_dir,
            model_name=vision_model_name,
            settings=settings,
            progress_callback=progress_callback,
        )
    if transcribe:
        _transcribe_scene_audio(
            scene_records=scene_records,
            audio_dir=audio_dir,
            model_name=asr_model_name,
            settings=settings,
            language=language,
            progress_callback=progress_callback,
        )

    if progress_callback:
        progress_callback("writing_output", 1, 1, "Writing output files")

    result = {
        "video": {
            "path": str(video_path.resolve()),
            "name": str(video.name),
            "fps": fps,
            "duration": video.duration.get_timecode() if video.duration is not None else None,
            "frame_size": {
                "width": int(video.frame_size[0]),
                "height": int(video.frame_size[1]),
            },
        },
        "config": {
            "detector": detector_name,
            "threshold": threshold,
            "min_scene_len_seconds": min_scene_len_seconds,
            "min_scene_len_frames": min_scene_len_frames,
            "frame_mode": frame_mode,
            "describe_visuals": describe_visuals,
            "vision_model": vision_model_name if describe_visuals else None,
            "transcribe": transcribe,
            "asr_model": asr_model_name if transcribe else None,
            "language": language,
        },
        "summary": {
            "scene_count": len(scene_records),
            "output_dir": str(video_output_dir.resolve()),
            "frames_dir": str(frames_dir.resolve()),
            "audio_dir": str(audio_dir.resolve()),
            "json_path": str(json_path.resolve()),
            "csv_path": str(csv_path.resolve()),
            "html_path": str(html_path.resolve()),
        },
        "scenes": [asdict(scene) for scene in scene_records],
    }

    _write_json(json_path, result)
    _write_csv(csv_path, scene_records)
    generate_html_report(analysis=result, output_path=html_path)
    return result


def _export_scene_frames(
    *,
    scene_list: list[tuple[Any, Any]],
    video_path: Path,
    fps: float,
    frames_dir: Path,
    frame_mode: str,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> list[SceneRecord]:
    total = len(scene_list)
    scene_records: list[SceneRecord] = []
    for index, (start, end) in enumerate(scene_list, start=1):
        if progress_callback:
            progress_callback("exporting_frames", index, total, f"Scene {index}/{total}")
        representative_frame = _choose_representative_frame(
            start_frame=int(start.get_frames()),
            end_frame=int(end.get_frames()),
            frame_mode=frame_mode,
        )
        screenshot_name = f"scene_{index:04d}.jpg"
        screenshot_path = frames_dir / screenshot_name
        _extract_frame(
            video_path=video_path,
            frame_number=representative_frame,
            fps=fps,
            destination=screenshot_path,
        )
        scene_records.append(
            _build_scene_record(
                scene_id=index,
                start=start,
                end=end,
                representative_frame=representative_frame,
                screenshot_path=f"frames/{screenshot_name}",
            )
        )
    return scene_records


def _export_scene_audio(
    *,
    scene_records: list[SceneRecord],
    video_path: Path,
    audio_dir: Path,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> None:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    if not probe.stdout.strip():
        for scene in scene_records:
            scene.audio_path = ""
            scene.notes = "Source video has no audio track."
        return
    total = len(scene_records)
    for i, scene in enumerate(scene_records, start=1):
        if progress_callback:
            progress_callback("extracting_audio", i, total, f"Scene {i}/{total}")
        destination = audio_dir / Path(scene.audio_path).name
        _run_ffmpeg_extract(
            video_path=video_path,
            output_path=destination,
            start_seconds=scene.start_seconds,
            duration_seconds=scene.duration_seconds,
        )


def _transcribe_scene_audio(*, scene_records, audio_dir, model_name, language,
                            progress_callback=None, settings=None):
    return transcribe_scenes(scene_records=scene_records, audio_dir=audio_dir,
        model_name=model_name, language=language, progress_callback=progress_callback,
        settings=settings or AppSettings.from_env())


def _describe_scene_frames(
    *,
    scene_records: list[SceneRecord],
    frames_dir: Path,
    model_name: str,
    settings: AppSettings | None = None,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
) -> None:
    image_paths = [frames_dir / Path(scene.screenshot_path).name for scene in scene_records]
    captions = describe_images_with_florence(
        image_paths=image_paths,
        model_name=model_name,
        task_prompt=(settings or AppSettings.from_env()).models.caption_task,
        settings=settings,
        progress_callback=progress_callback,
    )
    for scene, text in zip(scene_records, captions, strict=True):
        scene.visual_description = _normalize_caption(text)


def _build_scene_record(
    scene_id: int,
    start: Any,
    end: Any,
    representative_frame: int,
    screenshot_path: str,
) -> SceneRecord:
    start_seconds = start.get_seconds()
    end_seconds = end.get_seconds()
    return SceneRecord(
        scene_id=scene_id,
        start_timecode=start.get_timecode(),
        end_timecode=end.get_timecode(),
        start_seconds=round(start_seconds, 3),
        end_seconds=round(end_seconds, 3),
        duration_seconds=round(end_seconds - start_seconds, 3),
        start_frame=int(start.get_frames()),
        end_frame=int(end.get_frames()),
        representative_frame=representative_frame,
        screenshot_path=screenshot_path,
        audio_path=f"audio/scene_{scene_id:04d}.wav",
        shot_size="",
        visual_description="",
        camera_motion="",
        dialogue="",
        sound_effects="",
        bgm="",
        transcript_language="",
        transcript_confidence=None,
        notes="",
    )


def _write_csv(path: Path, scenes: list[SceneRecord]) -> None:
    fieldnames = list(SceneRecord.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for scene in scenes:
            writer.writerow(asdict(scene))
