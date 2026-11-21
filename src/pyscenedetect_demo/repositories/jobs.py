"""Job repository. Scheduling and event delivery belong to application services."""

from __future__ import annotations

import copy
import json
import logging
import shutil
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyscenedetect_demo.execution import EventHub
from pyscenedetect_demo.storage import write_json

logger = logging.getLogger(__name__)


@dataclass
class JobManager:
    data_dir: Path
    output_root: Path
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _jobs: dict[str, dict[str, Any]] = field(default_factory=dict)
    events: EventHub = field(default_factory=EventHub)
    load_error: str | None = None

    def _db_path(self):
        return self.data_dir / "web_jobs.json"

    def uploads_dir(self):
        path = self.data_dir / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    # Compatibility for integrations that used the old helper.
    _uploads_dir = uploads_dir

    @staticmethod
    def _decode(path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), dict):
            raise ValueError("Invalid job database")
        jobs = payload["jobs"]
        for key, job in jobs.items():
            if (
                not isinstance(job, dict)
                or job.get("id") != key
                or not all(
                    name in job for name in ("status", "config", "created_at", "video_path", "video_name")
                )
            ):
                raise ValueError("Invalid job record")
        return jobs

    def load(self):
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            path = self._db_path()
            if not path.exists():
                return
            try:
                self._jobs = self._decode(path)
            except (ValueError, TypeError, KeyError):
                # Preserve damaged bytes before any later save can replace them.
                quarantine = path.with_name(f"{path.name}.corrupt-{uuid.uuid4().hex}")
                shutil.copy2(path, quarantine)
                self.load_error = f"Damaged job database preserved at {quarantine.name}"
                logger.warning(self.load_error)
                backup = path.with_suffix(".json.bak")
                if backup.exists():
                    try:
                        self._jobs = self._decode(backup)
                        logger.warning("Recovered jobs from %s", backup)
                        return
                    except (ValueError, TypeError, KeyError):
                        logger.warning("Job backup is also unreadable; original files remain preserved")
                self._jobs = {}

    def _save_locked(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self._db_path()
        if path.exists():
            try:
                previous = self._decode(path)
            except (ValueError, TypeError, KeyError):
                previous = None
            if previous is not None:
                write_json(path.with_suffix(".json.bak"), {"version": 1, "jobs": previous})
        write_json(path, {"version": 1, "jobs": self._jobs})

    def save(self):
        with self._lock:
            self._save_locked()

    @contextmanager
    def _transaction(self):
        with self._lock:
            previous = copy.deepcopy(self._jobs)
            try:
                yield
                if self._jobs != previous:
                    self._save_locked()
            except Exception:
                self._jobs = previous
                raise

    def create_job(self, *, video_name, video_path, config):
        with self._transaction():
            job_id = uuid.uuid4().hex[:8]
            while job_id in self._jobs:
                job_id = uuid.uuid4().hex[:8]
            self._jobs[job_id] = {
                "id": job_id,
                "video_name": video_name,
                "video_path": str(video_path.resolve()),
                "status": "pending",
                "config": copy.deepcopy(config),
                "created_at": _utcnow(),
                "started_at": None,
                "completed_at": None,
                "output_dir": None,
                "scene_count": 0,
                "error": None,
            }
            return job_id

    def get_job(self, job_id):
        with self._lock:
            return copy.deepcopy(self._jobs.get(job_id))

    def list_jobs(self):
        with self._lock:
            return sorted(
                copy.deepcopy(list(self._jobs.values())), key=lambda job: job["created_at"], reverse=True
            )

    def update_job(self, job_id, updates):
        with self._transaction():
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.update(copy.deepcopy(updates))
            return copy.deepcopy(job)

    def delete_job(self, job_id):
        with self._transaction():
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job["status"] == "running":
                raise ValueError("Wait for processing to finish before deleting this job")
            self._jobs.pop(job_id)
        video = Path(job["video_path"]).resolve()
        if video.is_relative_to(self.uploads_dir().resolve()) and video.is_file():
            video.unlink(missing_ok=True)
        if job.get("output_dir"):
            output = Path(job["output_dir"]).resolve()
            root = self.output_root.resolve()
            if output != root and output.is_relative_to(root) and output.is_dir():
                shutil.rmtree(output)
        self.events.remove(job_id)
        return True

    def reset_orphaned_jobs(self):
        with self._transaction():
            for job in self._jobs.values():
                if job["status"] in {"pending", "running"}:
                    job.update(
                        status="failed",
                        error="Server was restarted while job was queued or running",
                        completed_at=_utcnow(),
                    )

    def get_or_create_queue(self, job_id):
        """Compatibility subscription; each caller receives its own event queue."""
        return self.events.subscribe(job_id)

    def remove_queue(self, job_id):
        self.events.remove(job_id)


def _utcnow():
    return datetime.now(timezone.utc).isoformat()
