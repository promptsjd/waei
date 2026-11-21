from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

_STATUS_LABELS = {
    "pending": "Pending",
    "running": "Running",
    "completed": "Completed",
    "failed": "Failed",
}
templates.env.globals["_status_label"] = lambda s: _STATUS_LABELS.get(s, s)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.get("/api/health")
    async def health(request: Request):
        import os
        return {"status": "ok", "application": "scene-scribe", "pid": os.getpid(),
                "revision": request.app.state.source_revision,
                "output_root": str(request.app.state.output_root)}

    # ==================================================================
    # Page routes
    # ==================================================================

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        mgr = request.app.state.job_manager
        jobs = mgr.list_jobs()
        return templates.TemplateResponse(request, "index.html", {"jobs": jobs, "defaults": request.app.state.settings})

    @router.get("/jobs/{job_id}", response_class=HTMLResponse)
    async def job_detail(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return templates.TemplateResponse(request, "job_detail.html", {"job": job})

    # ==================================================================
    # API routes
    # ==================================================================

    @router.post("/api/jobs")
    async def create_job(
        request: Request,
        video: UploadFile = File(...),
        detector: str | None = Form(None),
        threshold: float | None = Form(None),
        min_scene_len: float | None = Form(None),
        transcribe: bool = Form(False),
        asr_model: str | None = Form(None),
        language: str = Form(""),
        describe_visuals: bool = Form(False),
        vision_model: str | None = Form(None),
        mode: str = Form("analyze"),
    ):
        if not video.filename or not video.filename.lower().endswith(".mp4"):
            raise HTTPException(status_code=400, detail="Only MP4 files are supported")

        if mode not in ("analyze", "shotlist"):
            raise HTTPException(status_code=400, detail="mode must be 'analyze' or 'shotlist'")

        settings = request.app.state.settings
        detector = detector if detector is not None else settings.detection.detector
        threshold = threshold if threshold is not None else settings.detection.threshold
        min_scene_len = min_scene_len if min_scene_len is not None else settings.detection.min_scene_len_seconds
        asr_model = asr_model if asr_model is not None else settings.models.speech_model
        vision_model = vision_model if vision_model is not None else settings.models.vision_model
        service = request.app.state.job_service
        try:
            service.validate_options(detector, threshold, min_scene_len)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        if mode == "shotlist":
            config = {
                "detector": detector,
                "threshold": threshold,
                "min_scene_len_seconds": min_scene_len,
            }
            job_type = "shotlist"
        else:
            config = {
                "detector": detector,
                "threshold": threshold,
                "min_scene_len_seconds": min_scene_len,
                "transcribe": transcribe,
                "asr_model": asr_model if transcribe else None,
                "language": language or None,
                "describe_visuals": describe_visuals,
                "vision_model": vision_model if describe_visuals else None,
            }
            job_type = "analyze"

        try:
            return await service.create_upload(video, config, job_type)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, "Failed to save uploaded file") from exc

    @router.get("/api/jobs")
    async def list_jobs(request: Request):
        mgr = request.app.state.job_manager
        return mgr.list_jobs()

    @router.get("/api/jobs/{job_id}")
    async def get_job(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @router.delete("/api/jobs/{job_id}", status_code=204)
    async def delete_job(request: Request, job_id: str):
        try:
            ok = request.app.state.job_service.delete(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not ok:
            raise HTTPException(status_code=404, detail="Job not found")

    @router.post("/api/jobs/{job_id}/start")
    async def start_job(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"Job is {job['status']}, not pending")
        if not request.app.state.job_service.start(job_id):
            raise HTTPException(409, "Job is already queued")
        return {"status": "accepted"}

    @router.get("/api/jobs/{job_id}/events")
    async def job_events(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        queue = mgr.events.subscribe(job_id)

        async def event_generator():
            try:
                yield _sse_render(_sse_event("state", _strip_job_for_sse(job)))
                if job["status"] in ("completed", "failed"):
                    return
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield _sse_render(_sse_event("heartbeat", ""))
                        continue
                    if event is None:
                        break
                    yield _sse_render(event)
                    if event["event"] in ("complete", "failed"):
                        break
            except asyncio.CancelledError:
                pass
            finally:
                mgr.events.unsubscribe(job_id, queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/api/jobs/{job_id}/scenes")
    async def get_scenes(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job not completed")

        output_dir = job.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="No output directory")

        scenes_path = Path(output_dir) / "scenes.json"
        if not scenes_path.exists():
            raise HTTPException(status_code=404, detail="scenes.json not found")

        return json.loads(scenes_path.read_text(encoding="utf-8"))

    @router.post("/api/jobs/{job_id}/regenerate-report")
    async def regenerate_report(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job not completed")

        output_dir = job.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="No output directory")

        json_path = Path(output_dir) / "scenes.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="scenes.json not found")

        try:
            result = await request.app.state.job_service.regenerate(job)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {"html_path": str(result.resolve())}

    @router.get("/api/jobs/{job_id}/shots")
    async def get_shots(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job not completed")
        if job.get("job_type") != "shotlist":
            raise HTTPException(status_code=409, detail="Job is not a shotlist job")

        output_dir = job.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="No output directory")

        shots_path = Path(output_dir) / "shots.json"
        if not shots_path.exists():
            raise HTTPException(status_code=404, detail="shots.json not found")

        return json.loads(shots_path.read_text(encoding="utf-8"))

    @router.post("/api/jobs/{job_id}/regenerate-shotlist")
    async def regenerate_shotlist(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job not completed")
        if job.get("job_type") != "shotlist":
            raise HTTPException(status_code=409, detail="Job is not a shotlist job")

        output_dir = job.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="No output directory")

        json_path = Path(output_dir) / "shots.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="shots.json not found")

        try:
            html_path = await request.app.state.job_service.regenerate(job, shotlist=True)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return {"html_path": str(html_path.resolve())}

    @router.post("/api/jobs/{job_id}/enrich-visuals")
    async def enrich_visuals(request: Request, job_id: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job["status"] != "completed":
            raise HTTPException(status_code=409, detail="Job not completed")

        output_dir = job.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="No output directory")

        json_path = Path(output_dir) / "scenes.json"
        if not json_path.exists():
            raise HTTPException(status_code=404, detail="scenes.json not found")

        try:
            return await request.app.state.job_service.enrich(job_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/jobs/{job_id}/files/{file_path:path}")
    async def serve_job_file(request: Request, job_id: str, file_path: str):
        mgr = request.app.state.job_manager
        job = mgr.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        output_dir = job.get("output_dir")
        if not output_dir:
            raise HTTPException(status_code=404, detail="No output directory")

        resolved_root = Path(output_dir).resolve()
        requested = (resolved_root / file_path).resolve()
        if not requested.is_relative_to(resolved_root):
            raise HTTPException(status_code=403, detail="Path traversal denied")

        if not requested.exists() or not requested.is_file():
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(requested)

    return router


def _fire_background_job(request: Request, job_id: str) -> None:
    request.app.state.job_service.start(job_id)


def _sse_event(event: str, data: str | dict) -> dict[str, str]:
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    return {"event": event, "data": data}


def _sse_render(event: dict[str, str]) -> str:
    lines = []
    if event.get("event"):
        lines.append(f"event: {event['event']}")
    for line in event.get("data", "").split("\n"):
        lines.append(f"data: {line}")
    return "\n".join(lines) + "\n\n"


def _strip_job_for_sse(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "video_name": job["video_name"],
        "status": job["status"],
        "job_type": job.get("job_type", "analyze"),
        "scene_count": job.get("scene_count", 0),
        "shot_count": job.get("shot_count", 0),
        "error": job.get("error"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "completed_at": job.get("completed_at"),
        "config": job.get("config", {}),
    }


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
