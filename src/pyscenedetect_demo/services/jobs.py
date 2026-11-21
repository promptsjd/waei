"""Job execution, transitions, artifacts and progress delivery."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from pyscenedetect_demo.enrich_visuals import enrich_visual_descriptions
from pyscenedetect_demo.pipeline import run_scene_detection
from pyscenedetect_demo.progress import ProgressTracker
from pyscenedetect_demo.report import generate_html_report_from_json
from pyscenedetect_demo.shotlist import run_shotlist, regenerate_shotlist
from pyscenedetect_demo.repositories.jobs import _utcnow
from pyscenedetect_demo.uploads import save_upload, upload_name


class JobService:
    def __init__(
        self,
        repository,
        executor,
        settings,
        *,
        analyzer=run_scene_detection,
        shotlist=run_shotlist,
        enricher=enrich_visual_descriptions,
    ):
        self.repository = repository
        self.executor = executor
        self.settings = settings
        self.analyzer, self.shotlist, self.enricher = analyzer, shotlist, enricher

    @staticmethod
    def validate_options(detector, threshold, min_scene_len):
        if detector not in {"content", "adaptive"}:
            raise ValueError("Unsupported detector")
        if not math.isfinite(threshold) or threshold <= 0:
            raise ValueError("Threshold must be finite and greater than zero")
        if not math.isfinite(min_scene_len) or min_scene_len <= 0:
            raise ValueError("Minimum scene length must be finite and greater than zero")

    def busy(self, job_id):
        return self.executor.contains(f"job:{job_id}")

    async def create_upload(self, video, config, job_type):
        name = upload_name(video.filename)
        if not name.lower().endswith(".mp4"):
            raise ValueError("Only MP4 files are supported")
        mgr = self.repository
        job_id = mgr.create_job(video_name=name, video_path=mgr.uploads_dir() / "_placeholder", config=config)
        destination = mgr.uploads_dir() / f"{job_id}_{name}"
        try:
            await save_upload(video, destination)
            mgr.update_job(job_id, {"job_type": job_type, "video_path": str(destination.resolve())})
            self.start(job_id)
        except Exception:
            mgr.delete_job(job_id)
            destination.unlink(missing_ok=True)
            raise
        return {"job_id": job_id, "status": "pending"}

    def start(self, job_id):
        job = self.repository.get_job(job_id)
        if job is None or job["status"] != "pending":
            return False
        return self.executor.submit(f"job:{job_id}", lambda: self._run(job_id))

    def delete(self, job_id):
        if self.busy(job_id):
            raise ValueError("Wait for processing to finish before deleting this job")
        return self.repository.delete_job(job_id)

    def _progress(self, job_id, stages):
        loop = asyncio.get_running_loop()
        tracker = ProgressTracker(stages)

        def progress(stage, current, total, message=""):
            event = {"event": "progress", "data": json.dumps(tracker.event(stage, current, total, message))}
            loop.call_soon_threadsafe(self.repository.events.publish, job_id, event)

        return progress

    def _publish(self, job_id, event, data):
        self.repository.events.publish(job_id, {"event": event, "data": json.dumps(data)})

    def _failed(self, job_id, exc):
        self.repository.update_job(job_id, {"status": "failed", "error": str(exc), "completed_at": _utcnow()})
        self._publish(job_id, "failed", {"error": str(exc)})
        return {"status": "failed", "error": str(exc)}

    async def _run(self, job_id):
        mgr = self.repository
        job = mgr.get_job(job_id)
        if job is None or job["status"] != "pending":
            return
        config = job["config"]
        defaults = self.settings.detection
        shotlist = job.get("job_type") == "shotlist"
        stages = ["detecting", "exporting_frames"]
        if not shotlist:
            stages += ["extracting_audio"]
            if config.get("describe_visuals"):
                stages += ["describing"]
            if config.get("transcribe"):
                stages += ["transcribing"]
        stages += ["writing_output"]
        options = dict(
            video_path=Path(job["video_path"]),
            output_root=mgr.output_root,
            detector_name=config.get("detector", defaults.detector),
            threshold=config.get("threshold", defaults.threshold),
            min_scene_len_seconds=config.get("min_scene_len_seconds", defaults.min_scene_len_seconds),
            show_progress=False,
            progress_callback=self._progress(job_id, stages),
        )
        if not shotlist:
            options.update(
                frame_mode=defaults.frame_mode,
                transcribe=bool(config.get("transcribe")),
                asr_model_name=config.get("asr_model") or self.settings.models.speech_model,
                language=config.get("language"),
                describe_visuals=bool(config.get("describe_visuals")),
                vision_model_name=config.get("vision_model") or self.settings.models.vision_model,
                settings=self.settings,
            )
        mgr.update_job(job_id, {"status": "running", "started_at": _utcnow(), "error": None})
        try:
            result = await asyncio.to_thread(self.shotlist if shotlist else self.analyzer, **options)
            count_key = "shot_count" if shotlist else "scene_count"
            mgr.update_job(
                job_id,
                {
                    "status": "completed",
                    "completed_at": _utcnow(),
                    count_key: result["summary"][count_key],
                    "output_dir": result["summary"]["output_dir"],
                },
            )
            self._publish(job_id, "complete", {"job_id": job_id})
        except Exception as exc:
            self._failed(job_id, exc)

    async def regenerate(self, job, *, shotlist=False):
        directory = Path(job["output_dir"])

        async def work():
            if shotlist:
                return await asyncio.to_thread(regenerate_shotlist, json_path=directory / "shots.json")
            return await asyncio.to_thread(
                generate_html_report_from_json, json_path=directory / "scenes.json"
            )

        return await self.executor.call(f"job:{job['id']}", work)

    async def enrich(self, job_id):
        job = self.repository.get_job(job_id)
        if job is None or job["status"] != "completed" or self.busy(job_id):
            raise ValueError("Job is not ready for visual enrichment")
        config = job.get("config", {})
        model = config.get("vision_model") or self.settings.models.vision_model
        path = Path(job["output_dir"]) / "scenes.json"

        async def work():
            try:
                await asyncio.to_thread(
                    self.enricher,
                    json_path=path,
                    model_name=model,
                    settings=self.settings,
                    progress_callback=self._progress(job_id, ["describing"]),
                )
                config.update(describe_visuals=True, vision_model=model)
                self.repository.update_job(
                    job_id, {"status": "completed", "completed_at": _utcnow(), "config": config}
                )
                self._publish(job_id, "complete", {"job_id": job_id})
                return {"status": "completed"}
            except Exception as exc:
                return self._failed(job_id, exc)

        self.repository.update_job(job_id, {"status": "running", "started_at": _utcnow(), "error": None})
        return await self.executor.call(f"job:{job_id}", work)
