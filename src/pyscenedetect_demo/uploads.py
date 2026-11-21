"""Streaming upload storage shared by analysis and editor services."""
import hashlib
import uuid
from pathlib import Path


def upload_name(filename):
    return Path((filename or "").replace("\\", "/")).name


async def save_upload(upload, destination):
    destination = Path(destination)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.upload")
    digest, size = hashlib.sha256(), 0
    try:
        with temporary.open("wb") as handle:
            while block := await upload.read(1024 * 1024):
                handle.write(block)
                digest.update(block)
                size += len(block)
        if not size:
            raise ValueError("An uploaded video is empty.")
        temporary.replace(destination)
        return {"sha256": digest.hexdigest(), "size": size}
    finally:
        temporary.unlink(missing_ok=True)
        await upload.close()
