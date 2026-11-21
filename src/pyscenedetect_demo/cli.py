from __future__ import annotations

import argparse
from pathlib import Path
from pyscenedetect_demo.settings import AppSettings, DEFAULT_DETECTION, DEFAULT_MODELS

from pyscenedetect_demo.pipeline import run_scene_detection
from pyscenedetect_demo.shotlist import run_shotlist


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scene-analyzer",
        description="Detect scenes in an MP4 file and export scene metadata.",
    )
    parser.add_argument("video_path", help="Path to the input MP4 file.")
    parser.add_argument(
        "--output",
        default=str(AppSettings.from_env().output_root),
        help="Base output directory. Default: %(default)s",
    )
    parser.add_argument(
        "--detector",
        choices=("content", "adaptive"),
        default=DEFAULT_DETECTION.detector,
        help="Scene detection algorithm. Default: %(default)s",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_DETECTION.threshold,
        help="Detection threshold. Default: %(default)s",
    )
    parser.add_argument(
        "--min-scene-len",
        type=float,
        default=DEFAULT_DETECTION.min_scene_len_seconds,
        help="Minimum scene length in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--frame-mode",
        choices=("middle",),
        default=DEFAULT_DETECTION.frame_mode,
        help="Representative frame selection strategy. Default: %(default)s",
    )
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="Run local speech-to-text on each scene audio clip.",
    )
    parser.add_argument(
        "--asr-model",
        default=DEFAULT_MODELS.speech_model,
        help="faster-whisper model size/name. Default: %(default)s",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language hint for ASR, for example `zh` or `en`.",
    )
    parser.add_argument(
        "--describe-visuals",
        action="store_true",
        help="Run local image captioning on each representative scene frame.",
    )
    parser.add_argument(
        "--vision-model",
        default=DEFAULT_MODELS.vision_model,
        help="Hugging Face image captioning model. Default: %(default)s",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show PySceneDetect progress bar if available.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = run_scene_detection(
            video_path=Path(args.video_path),
            output_root=Path(args.output),
            detector_name=args.detector,
            threshold=args.threshold,
            min_scene_len_seconds=args.min_scene_len,
            frame_mode=args.frame_mode,
            transcribe=args.transcribe,
            asr_model_name=args.asr_model,
            language=args.language,
            describe_visuals=args.describe_visuals,
            vision_model_name=args.vision_model,
            show_progress=args.show_progress,
        )
    except Exception as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")

    print(f"Video: {result['video']['path']}")
    print(f"Scenes detected: {result['summary']['scene_count']}")
    print(f"Output directory: {result['summary']['output_dir']}")
    print(f"Audio directory: {result['summary']['audio_dir']}")
    print(f"JSON: {result['summary']['json_path']}")
    print(f"CSV: {result['summary']['csv_path']}")
    print(f"HTML: {result['summary']['html_path']}")
    return 0


def build_shotlist_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scene-shotlist",
        description="Generate a pure shot list (start/end frame thumbnails) from an MP4 file.",
    )
    parser.add_argument("video_path", help="Path to the input MP4 file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Output directory. Default: same directory as the video file.",
    )
    parser.add_argument(
        "--detector",
        choices=("content", "adaptive"),
        default=DEFAULT_DETECTION.detector,
        help="Scene detection algorithm. Default: %(default)s",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_DETECTION.threshold,
        help="Detection threshold. Default: %(default)s",
    )
    parser.add_argument(
        "--min-scene-len",
        type=float,
        default=DEFAULT_DETECTION.min_scene_len_seconds,
        help="Minimum scene length in seconds. Default: %(default)s",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show PySceneDetect progress bar if available.",
    )
    return parser


def shotlist_main(argv: list[str] | None = None) -> int:
    parser = build_shotlist_parser()
    args = parser.parse_args(argv)

    video_path = Path(args.video_path).resolve()
    output_root = Path(args.output) if args.output else video_path.parent

    try:
        result = run_shotlist(
            video_path=video_path,
            output_root=output_root,
            detector_name=args.detector,
            threshold=args.threshold,
            min_scene_len_seconds=args.min_scene_len,
            show_progress=args.show_progress,
        )
    except Exception as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")

    print(f"Video: {result['video']['path']}")
    print(f"Shots detected: {result['summary']['shot_count']}")
    print(f"Output directory: {result['summary']['output_dir']}")
    print(f"HTML: {result['summary']['html_path']}")
    print(f"PDF:  {result['summary']['pdf_path']}")
    return 0
