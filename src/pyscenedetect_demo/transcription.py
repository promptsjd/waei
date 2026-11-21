"""Speech adapters retain distinct scene and word-level decoding policies."""

from __future__ import annotations

import math
import wave


def whisper_model(settings, *, word_level=False, name=None):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "faster-whisper is not installed. Reinstall dependencies with `pip install -e .`."
        ) from exc
    options = {"device": settings.models.device, "compute_type": settings.models.compute_type}
    if word_level:
        options["cpu_threads"] = settings.models.cpu_threads
    return WhisperModel(
        settings.speech_model_path(name or settings.models.speech_model, require_local=word_level), **options
    )


class WordTranscriber:
    def __init__(self, settings):
        self.settings = settings
        self.model = whisper_model(settings, word_level=True)

    def transcribe(self, path, language=None):
        segments, info = self.model.transcribe(
            str(path),
            word_timestamps=True,
            beam_size=self.settings.models.editor_beam_size,
            language=language,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        words = [
            {
                "start": float(word.start),
                "end": float(word.end),
                "word": word.word,
                "probability": float(word.probability),
            }
            for segment in segments
            for word in segment.words or []
        ]
        return words, info.language


def transcribe_scenes(*, scene_records, audio_dir, model_name, language, settings, progress_callback=None):
    scenes = [scene for scene in scene_records if scene.audio_path]
    if not scenes:
        return
    model = whisper_model(settings, name=model_name)
    from pathlib import Path

    for index, scene in enumerate(scenes, 1):
        if progress_callback:
            progress_callback("transcribing", index, len(scenes), f"Scene {index}/{len(scenes)}")
        segments, info = model.transcribe(
            str(audio_dir / Path(scene.audio_path).name),
            language=language,
            beam_size=settings.models.scene_beam_size,
            vad_filter=True,
            condition_on_previous_text=False,
        )
        segments = list(segments)
        scene.dialogue = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        probabilities = [math.exp(min(0.0, segment.avg_logprob)) for segment in segments]
        scene.transcript_confidence = (
            round(sum(probabilities) / len(probabilities), 4) if probabilities else None
        )
        scene.transcript_language = info.language or ""


def has_audible_signal(path, amplitude):
    import numpy as np

    with wave.open(str(path), "rb") as audio:
        while block := audio.readframes(16000):
            if np.max(np.abs(np.frombuffer(block, dtype=np.int16).astype(np.int32))) > amplitude:
                return True
    return False
