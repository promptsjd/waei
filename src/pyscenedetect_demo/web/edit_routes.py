"""Editor HTTP transport. State transitions and uploads belong to EditorService."""

from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from pyscenedetect_demo.storage import project_state
from pyscenedetect_demo.editor.project_names import DuplicateProjectName
from pyscenedetect_demo.editor.preview import browser_preview


class WorkspaceChanges(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str | None = None
    topic: str | None = None
    context: str | None = None
    language: str | None = None
    allow_reorder: bool | None = None
    describe_visuals: bool | None = None
    asset_ids: list[str] | None = None
    ai_response: str | None = None
    ai_response_input_id: str | None = None
    revision: int | None = None


def workspace_error(exc):
    status = 404 if isinstance(exc, FileNotFoundError) else 409 if isinstance(exc, (DuplicateProjectName, RuntimeError)) else 400
    return HTTPException(status, str(exc))


def create_edit_router():
    router = APIRouter()
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    def folder_for(request, project_id):
        try:
            return request.app.state.editor_service.folder(project_id)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/editor", response_class=HTMLResponse)
    async def editor_page(request: Request):
        return templates.TemplateResponse(request, "editor.html", {})

    @router.get("/api/editor/projects")
    async def list_projects(request: Request):
        return request.app.state.editor_service.list_projects()

    @router.post("/api/editor/projects/draft")
    async def create_draft(request: Request, name: str = Form("")):
        try:
            return request.app.state.editor_service.create_draft(name)
        except DuplicateProjectName as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/editor/workspace")
    async def create_workspace(request: Request, workspace: str = Form("{}"), videos: list[UploadFile] | None = File(None)):
        try:
            changes = WorkspaceChanges.model_validate_json(workspace).model_dump(exclude_unset=True, exclude_none=True)
            return await request.app.state.editor_service.create_workspace(changes.get("name"), changes, videos or [])
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            raise workspace_error(exc) from exc

    @router.patch("/api/editor/projects/{project_id}/workspace")
    async def save_workspace(request: Request, project_id: str, changes: WorkspaceChanges):
        try:
            return request.app.state.editor_service.save_workspace(project_id, changes.model_dump(exclude_unset=True, exclude_none=True))
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            raise workspace_error(exc) from exc

    @router.post("/api/editor/projects/{project_id}/clips")
    async def add_clips(request: Request, project_id: str, videos: list[UploadFile] = File(...)):
        try:
            return await request.app.state.editor_service.add_clips(project_id, videos)
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            raise workspace_error(exc) from exc

    @router.post("/api/editor/projects/{project_id}/analyze")
    async def analyze_clips(request: Request, project_id: str):
        try:
            return request.app.state.editor_service.start_analysis(project_id)
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            raise workspace_error(exc) from exc

    @router.get("/api/editor/samples/{filename}")
    async def sample(request: Request, filename: str):
        if filename not in {"speech-demo.mp4", "speech-demo-second.mp4"}:
            raise HTTPException(404, "Sample not found")
        path = request.app.state.settings.sample_dir / filename
        if not path.is_file():
            raise HTTPException(404, "This sample clip is not installed. Choose your own MP4 files instead.")
        return FileResponse(path, media_type="video/mp4", filename=filename)

    @router.post("/api/editor/projects")
    async def create_project(
        request: Request,
        videos: list[UploadFile] = File(...),
        topic: str = Form(""),
        context: str = Form(""),
        allow_reorder: bool = Form(False),
        describe_visuals: bool = Form(True),
        language: str = Form(""),
        project_id: str = Form(""),
    ):
        try:
            return await request.app.state.editor_service.create(
                videos,
                topic=topic,
                context=context,
                allow_reorder=allow_reorder,
                describe_visuals=describe_visuals,
                language=language,
                project_id=project_id or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/editor/projects/{project_id}")
    async def get_project(request: Request, project_id: str):
        folder_for(request, project_id)
        try:
            return request.app.state.editor_service.view(project_id)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, "Project data could not be read; its files are preserved.") from exc

    @router.delete("/api/editor/projects/{project_id}", status_code=204)
    async def delete_project(request: Request, project_id: str):
        try:
            await run_in_threadpool(request.app.state.editor_service.delete, project_id)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            raise workspace_error(exc) from exc
        except OSError as exc:
            raise HTTPException(409, "Could not delete this project. Close its video preview and try again.") from exc
        return Response(status_code=204)

    @router.get("/api/editor/projects/{project_id}/prompt", response_class=PlainTextResponse)
    async def get_prompt(request: Request, project_id: str):
        folder_for(request, project_id)
        try:
            return request.app.state.editor_service.prompt(project_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/editor/projects/{project_id}/plan")
    async def apply_plan(request: Request, project_id: str):
        folder_for(request, project_id)
        try:
            text = (await request.body()).decode("utf-8")
            return request.app.state.editor_service.apply_plan(project_id, text)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/editor/projects/{project_id}/render")
    async def render(request: Request, project_id: str):
        folder_for(request, project_id)
        try:
            return request.app.state.editor_service.render(project_id)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/editor/projects/{project_id}/download/{filename}")
    async def download(request: Request, project_id: str, filename: str):
        if filename not in {"prompt.txt", "analysis.json", "plan.json", "resolved.json", "edited-script.txt"}:
            raise HTTPException(404, "File not found")
        folder_for(request, project_id)
        path = request.app.state.editor_service.artifact(project_id, filename)
        if not path.is_file():
            raise HTTPException(404, "File not ready")
        return FileResponse(path, filename=filename)

    @router.get("/api/editor/projects/{project_id}/video")
    async def video(request: Request, project_id: str, download: bool = False, preview: bool = False):
        folder = folder_for(request, project_id)
        state = project_state(folder)
        output_file = (state.get("last_video") or {}).get("file") or state.get("output_file")
        if not output_file:
            raise HTTPException(409, "Render the video first.")
        path = (folder / output_file).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise HTTPException(404, "Rendered video not found")
        if preview and not download:
            try:
                path = await run_in_threadpool(browser_preview, path)
            except (OSError, ValueError) as exc:
                raise HTTPException(503, "Could not prepare preview audio. Try again or download the video.") from exc
        return FileResponse(path, media_type="video/mp4", filename="edited.mp4" if download else None)

    return router
