"""Typed application defaults. Processing policy is independent of HTTP and CLI."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

INSTALL_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DetectionSettings:
    detector: str = "content"
    threshold: float = 27.0
    min_scene_len_seconds: float = 0.8
    frame_mode: str = "middle"


@dataclass(frozen=True)
class ModelSettings:
    speech_model: str = "tiny"
    vision_model: str = "microsoft/Florence-2-base"
    device: str = "cpu"
    compute_type: str = "int8"
    cpu_threads: int = 4
    scene_beam_size: int = 1
    editor_beam_size: int = 5
    caption_task: str = "<DETAILED_CAPTION>"
    caption_tokens: int = 128
    caption_beams: int = 3


@dataclass(frozen=True)
class SegmentationPolicy:
    # Legacy tuning fields remain accepted for integrations. Sentence grouping
    # no longer uses fillers, pauses or size limits as independent cut points.
    fillers: frozenset[str] = frozenset({"um", "uh", "erm", "umm", "uhh"})
    pause_ms: int = 450
    max_words: int = 12
    max_phrase_ms: int = 4500
    leading_padding_ms: int = 120
    trailing_padding_ms: int = 180
    silence_ms: int = 350
    uncertain_ms: int = 120
    audible_amplitude: int = 500


@dataclass(frozen=True)
class RenderProfile:
    fps: int = 30
    max_dimension: int = 1280
    audio_rate: int = 48000
    video_codec: str = "libx264"
    preset: str = "veryfast"
    crf: int = 20
    audio_bitrate: str = "160k"
    minimum_tolerance_ms: int = 150
    tolerance_per_range_ms: int = 45


@dataclass(frozen=True)
class AppSettings:
    output_root: Path = Path("output")
    model_dir: Path = INSTALL_ROOT / "models"
    sample_dir: Path = INSTALL_ROOT / "samples"
    host: str = "127.0.0.1"
    port: int = 8080
    max_parallel_jobs: int = 1
    enable_editor: bool = True
    detection: DetectionSettings = field(default_factory=DetectionSettings)
    models: ModelSettings = field(default_factory=ModelSettings)
    segmentation: SegmentationPolicy = field(default_factory=SegmentationPolicy)
    render: RenderProfile = field(default_factory=RenderProfile)

    def __post_init__(self):
        if self.max_parallel_jobs < 1:
            raise ValueError("max_parallel_jobs must be positive")
        if self.render.fps <= 0 or self.render.audio_rate <= 0:
            raise ValueError("Render frame and audio rates must be positive")
        if self.models.cpu_threads < 1:
            raise ValueError("CPU thread count must be positive")

    @classmethod
    def from_env(cls):
        defaults = cls()
        return cls(
            output_root=Path(os.environ.get("SCENE_SCRIBE_OUTPUT", defaults.output_root)),
            model_dir=Path(os.environ.get("SCENE_SCRIBE_MODELS", defaults.model_dir)),
            sample_dir=Path(os.environ.get("SCENE_SCRIBE_SAMPLES", defaults.sample_dir)),
            host=os.environ.get("SCENE_SCRIBE_HOST", defaults.host),
            port=int(os.environ.get("SCENE_SCRIBE_PORT", defaults.port)),
            max_parallel_jobs=int(os.environ.get("SCENE_SCRIBE_WORKERS", defaults.max_parallel_jobs)),
            enable_editor=os.environ.get("SCENE_SCRIBE_EDITOR", "1").lower() not in {"0", "false", "no"},
        )

    def speech_model_path(self, name: str, *, require_local: bool = False) -> str:
        local = self.model_dir / f"faster-whisper-{name}"
        return str(local) if require_local or (local / "model.bin").is_file() else name

    def vision_model_path(self, name: str) -> str:
        local = self.model_dir / name.rsplit("/", 1)[-1]
        return str(local) if (local / "config.json").is_file() else name


DEFAULT_DETECTION = DetectionSettings()
DEFAULT_MODELS = ModelSettings()


if __name__ == "__main__":
    # Launchers consume the same configuration as Python entry points.
    import json
    from pyscenedetect_demo.runtime import source_revision

    settings = AppSettings.from_env()
    print(
        json.dumps(
            {
                "host": settings.host,
                "port": settings.port,
                "output_root": str(settings.output_root.resolve()),
                "model_dir": str(settings.model_dir.resolve()),
                "revision": source_revision(),
            }
        )
    )
