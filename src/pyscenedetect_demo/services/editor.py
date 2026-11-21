"""Editor use cases and state transitions, independent of HTTP."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone

from pyscenedetect_demo.editor import analysis, plans, prompting, rendering
from pyscenedetect_demo.editor.project_names import available_name
from pyscenedetect_demo.storage import ProjectRepository, list_project_states, path_lock, write_json
from pyscenedetect_demo.uploads import save_upload, upload_name
from .editor_workspace import WorkspaceProjects

logger = logging.getLogger(__name__)


class EditorService(WorkspaceProjects):
    def __init__(self, root, executor, settings):
        self.root, self.executor, self.settings = root, executor, settings

    def folder(self, project_id):
        if not re.fullmatch(r"[a-f0-9]{32}", project_id):
            raise FileNotFoundError("Project not found")
        folder = self.root / project_id
        if not (folder / "project.json").is_file():
            raise FileNotFoundError("Project not found")
        return folder

    def list_projects(self):
        result = [
            {key: state.get(key) for key in ("id", "created_at", "status", "message", "name")}
            for _, state in list_project_states(self.root)
        ]
        return sorted(result, key=lambda item: item["created_at"], reverse=True)

    def create_draft(self, name=None):
        # Name checking and reservation must be one operation across concurrent requests.
        with path_lock(self.root):
            name = available_name(self.list_projects(), name)
            project_id = uuid.uuid4().hex
            state = {
                "id": project_id, "name": name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "draft", "progress": 0, "message": "", "error": None,
                "assets": [], "output_file": None,
                "topic": "", "context": "", "allow_reorder": False,
                "describe_visuals": True, "language": "",
            }
            write_json(self.root / project_id / "project.json", state)
        return {"id": project_id, "name": name}

    def recover_interrupted(self):
        for folder, state in list_project_states(self.root):
            if state["status"] in {"analyzing", "rendering"}:
                try:
                    ProjectRepository(folder).update(
                        status="failed",
                        error="Server restarted during processing. Start a new analysis, or render the validated plan again.",
                    )
                except (OSError, ValueError):
                    logger.exception("Could not recover interrupted project %s", folder)

    def delete(self, project_id):
        with path_lock(self.root):
            folder = self.folder(project_id)
            # Only a direct project directory may be removed, never a link target.
            if folder.resolve() != self.root.resolve() / project_id or folder.is_symlink():
                raise ValueError("Project directory is outside the project library.")
            with ProjectRepository(folder).locked() as repository:
                self._idle(project_id, repository.state())
                shutil.rmtree(folder)

    def _schedule(self, folder, operation):
        async def work():
            try:
                await asyncio.to_thread(operation, folder, settings=self.settings)
            except Exception as exc:
                ProjectRepository(folder).update(
                    status="failed", error=str(exc), message="Processing failed. See the error below."
                )

        return self.executor.submit(f"editor:{folder.name}", work)

    async def create(
        self, videos, *, topic="", context="", allow_reorder=False, describe_visuals=True, language="", project_id=None
    ):
        if not videos or any(not upload_name(video.filename).lower().endswith(".mp4") for video in videos):
            for video in videos:
                await video.close()
            raise ValueError("Choose one or more MP4 videos.")
        new_project = project_id is None
        folder = None
        claimed = False
        uploaded_paths = []
        assets = []
        try:
            if new_project:
                project_id = self.create_draft()["id"]
            folder = self.folder(project_id)
            repository = ProjectRepository(folder)
            with repository.locked():
                if repository.state()["status"] != "draft" or self.executor.contains(f"editor:{project_id}"):
                    raise RuntimeError("Create a new project to analyze new clips. Existing work is preserved.")
                repository.update(status="analyzing", message="Uploading clips...", error=None)
                claimed = True
            (folder / "media").mkdir(exist_ok=True)
            for index, video in enumerate(videos):
                asset_id = f"asset_{index + 1:04d}"
                destination = folder / "media" / f"{asset_id}.mp4"
                uploaded_paths.append(destination)
                details = await save_upload(video, destination)
                assets.append({"id": asset_id, "name": upload_name(video.filename), **details})
            repository.update(
                status="analyzing", progress=0, message="Waiting for local CPU analysis...",
                error=None, assets=assets, describe_visuals=describe_visuals,
                language=language.strip(), topic=topic.strip(), context=context.strip(),
                allow_reorder=allow_reorder,
            )
            self._schedule(folder, analysis.analyze_project)
        except Exception:
            # Only remove the newly allocated project, never an existing one.
            if new_project and folder and folder.resolve().parent == self.root.resolve():
                shutil.rmtree(folder)
            elif claimed:
                for path in uploaded_paths:
                    path.unlink(missing_ok=True)
                repository.update(status="draft", assets=[], message="", error=None)
            raise
        finally:
            for video in videos:
                await video.close()
        return {"id": project_id}

    def view(self, project_id):
        return self.workspace_view(project_id)

    def prompt(self, project_id):
        folder = self.folder(project_id)
        if not ProjectRepository(folder).view()["analysis_current"]:
            raise ValueError("Analyze clips to update the prompt first.")
        return prompting.write_prompt(folder)

    def apply_plan(self, project_id, text):
        folder = self.folder(project_id)
        with ProjectRepository(folder).locked() as repository:
            state = repository.state()
            if state["status"] in {"analyzing", "rendering"} or self.executor.contains(
                f"editor:{project_id}"
            ):
                raise RuntimeError("Wait for the current processing step to finish.")
            if not ProjectRepository(folder).view()["analysis_current"]:
                raise RuntimeError("Wait for the current processing step to finish.")
            resolved = plans.accept_plan(folder, text)
            repository.update(ai_response=text, ai_response_input_id=repository.read_artifact("analysis.json")["input_id"])
            return resolved

    def render(self, project_id):
        folder = self.folder(project_id)
        with ProjectRepository(folder).locked() as repository:
            state = repository.state()
            if (
                state["status"] in {"analyzing", "rendering"}
                or self.executor.contains(f"editor:{project_id}")
                or not repository.artifact_path("resolved.json").is_file()
                or not repository.view()["plan_current"]
            ):
                raise RuntimeError("Validate an edit plan before rendering.")
            if not repository.read_artifact("resolved.json")["timeline"]:
                raise ValueError("This plan retains no video. Paste a plan that retains at least one unit.")
            repository.update(
                status="rendering", progress=0, message="Waiting to render on CPU...", error=None
            )
            self._schedule(folder, rendering.render_project)
        return {"status": "rendering"}

    def artifact(self, project_id, filename):
        folder = self.folder(project_id)
        if filename == "prompt.txt" and (folder / "analysis.json").is_file():
            prompting.write_prompt(folder)
        return ProjectRepository(folder).artifact_path(filename)
