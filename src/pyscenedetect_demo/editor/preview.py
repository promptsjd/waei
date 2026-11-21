"""Cached preview audio for embedded players that cannot decode AAC."""

import uuid
from pathlib import Path

from pyscenedetect_demo.media import run_command
from pyscenedetect_demo.storage import path_lock


def browser_preview(source: Path) -> Path:
    """Copy the rendered picture and encode MP3 audio; preserve the export.

    Each render has its own immutable directory, so an adjacent preview can be
    reused for playback, seeking, and reopened projects without becoming stale.
    """
    source = Path(source)
    preview = source.with_name(f"{source.stem}.preview.mp4")
    with path_lock(preview):
        if preview.is_file():
            return preview
        temporary = preview.with_name(f".{preview.stem}.{uuid.uuid4().hex}.mp4")
        try:
            run_command([
                "ffmpeg", "-y", "-v", "error", "-i", str(source),
                "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy",
                "-c:a", "libmp3lame", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart", str(temporary),
            ])
            temporary.replace(preview)
        finally:
            temporary.unlink(missing_ok=True)
    return preview
