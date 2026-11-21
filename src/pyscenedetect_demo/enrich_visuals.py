from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable
from pathlib import Path

from pyscenedetect_demo.report import generate_html_report
from pyscenedetect_demo.vision import describe_images_with_florence
from pyscenedetect_demo.captions import normalize_caption as _normalize_caption
from pyscenedetect_demo.settings import AppSettings, DEFAULT_MODELS
from pyscenedetect_demo.storage import write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scene-visuals",
        description="Add visual descriptions to an existing scenes.json analysis.",
    )
    parser.add_argument("json_path", help="Path to the existing scenes.json file.")
    parser.add_argument(
        "--vision-model",
        default=DEFAULT_MODELS.vision_model,
        help="Hugging Face Florence-2 model. Default: %(default)s",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    json_path = Path(args.json_path)
    try:
        enrich_visual_descriptions(
            json_path=json_path,
            model_name=args.vision_model,
        )
    except Exception as exc:
        parser.exit(status=1, message=f"Error: {exc}\n")

    print(f"Updated JSON: {json_path.resolve()}")
    print(f"Updated CSV: {json_path.with_name('scenes.csv').resolve()}")
    print(f"Updated HTML: {json_path.with_name('report.html').resolve()}")
    return 0


def enrich_visual_descriptions(
    *,
    json_path: Path,
    model_name: str,
    progress_callback: Callable[[str, int, int, str], None] | None = None,
    settings: AppSettings | None = None,
) -> None:
    analysis = json.loads(json_path.read_text(encoding="utf-8"))
    output_dir = json_path.parent
    frames_dir = output_dir / "frames"
    scenes = analysis["scenes"]

    image_paths = [frames_dir / Path(scene["screenshot_path"]).name for scene in scenes]
    captions = describe_images_with_florence(
        image_paths=image_paths,
        model_name=model_name,
        task_prompt=(settings or AppSettings.from_env()).models.caption_task,
        settings=settings,
        progress_callback=progress_callback,
    )

    for scene, caption in zip(scenes, captions, strict=True):
        scene["visual_description"] = _normalize_caption(caption)
        scene.setdefault("shot_size", "")
        scene.setdefault("camera_motion", "")
        scene.setdefault("sound_effects", "")
        scene.setdefault("bgm", "")
        scene.setdefault("notes", "")

    analysis.setdefault("config", {})
    analysis["config"]["describe_visuals"] = True
    analysis["config"]["vision_model"] = model_name

    analysis.setdefault("summary", {})
    analysis["summary"]["json_path"] = str(json_path.resolve())
    analysis["summary"]["csv_path"] = str((output_dir / "scenes.csv").resolve())
    analysis["summary"]["html_path"] = str((output_dir / "report.html").resolve())

    write_json(json_path, analysis)
    _write_csv(output_dir / "scenes.csv", scenes)
    generate_html_report(analysis=analysis, output_path=output_dir / "report.html")


def _write_csv(path: Path, scenes: list[dict[str, object]]) -> None:
    if not scenes:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(scenes[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(scenes)
