"""Identify the source revision loaded by a long-running local server."""
import hashlib
from pathlib import Path


def source_revision():
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".html", ".js", ".css", ".json", ".md"}:
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
    return digest.hexdigest()
