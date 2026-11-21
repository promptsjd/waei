"""Autosaved editor content, source imports, and analysis freshness."""

import uuid
from pyscenedetect_demo.editor import analysis
from pyscenedetect_demo.editor.project_names import clean_name
from pyscenedetect_demo.editor.segmentation import SEGMENTATION_VERSION
from pyscenedetect_demo.editor.workspace import signature, preserve_baseline, FIELDS
from pyscenedetect_demo.storage import ProjectRepository, path_lock
from pyscenedetect_demo.uploads import upload_name, save_upload


class WorkspaceProjects:
    def _idle(self, project_id, state):
        if state["status"] in {"analyzing", "rendering"} or self.executor.contains(f"editor:{project_id}"):
            raise RuntimeError("Wait for processing to finish before changing this project.")

    def save_workspace(self, project_id, changes):
        repository = ProjectRepository(self.folder(project_id))
        with path_lock(self.root), repository.locked():
            state = repository.state()
            self._idle(project_id, state)
            expected = changes.get("revision")
            if expected is not None and expected != state.get("workspace_revision", 0):
                raise RuntimeError("This project changed in another window. Reopen it before making more changes.")
            updates = preserve_baseline(repository, state)
            for key in FIELDS:
                if key in changes:
                    value = changes[key]
                    updates[key] = value.strip() if isinstance(value, str) else value
            if changes.get("name", "").strip() and clean_name(changes["name"]) != state["name"]:
                raise ValueError("Saved project names cannot be changed. Start a new project to use another name.")
            if "asset_ids" in changes:
                current = {asset["id"]: asset for asset in state.get("assets", [])}
                requested = changes["asset_ids"]
                if len(set(requested)) != len(requested) or any(identifier not in current for identifier in requested):
                    raise ValueError("The clip list changed. Reopen this project and try again.")
                updates["assets"] = [current[identifier] for identifier in requested]
            for key in ("ai_response", "ai_response_input_id"):
                if key in changes:
                    updates[key] = changes[key]
            updated = {**state, **updates}
            if signature(updated) != signature(state):
                updates.update(status="draft", error=None, message="")
            updates["workspace_revision"] = state.get("workspace_revision", 0) + 1
            repository.update(**updates)
        return self.workspace_view(project_id)

    async def add_clips(self, project_id, videos):
        repository = ProjectRepository(self.folder(project_id))
        destinations = []

        async def store():
            state = repository.state()
            library = {**state.get("asset_library", {}), **{asset["id"]: asset for asset in state.get("assets", [])}}
            assets = list(state.get("assets", []))
            baseline = preserve_baseline(repository, state)
            (repository.folder / "media").mkdir(exist_ok=True)
            try:
                for upload in videos:
                    identifier = "asset_" + uuid.uuid4().hex
                    path = repository.folder / "media" / f"{identifier}.mp4"
                    destinations.append(path)
                    details = await save_upload(upload, path)
                    prior = next((asset for asset in library.values() if asset.get("sha256") == details["sha256"]), None)
                    if prior:
                        path.unlink(missing_ok=True)
                        asset = prior
                    else:
                        asset = {"id": identifier, "name": upload_name(upload.filename), **details}
                        library[identifier] = asset
                    if asset["id"] not in {item["id"] for item in assets}:
                        assets.append(asset)
                updates = {**baseline, "assets": assets, "asset_library": library,
                           "workspace_revision": state.get("workspace_revision", 0) + 1}
                if signature({**state, **updates}) != signature(state):
                    updates.update(status="draft", error=None, message="")
                repository.update(**updates)
            except BaseException:
                for path in destinations:
                    path.unlink(missing_ok=True)
                raise

        try:
            if not videos or any(not upload_name(video.filename).lower().endswith(".mp4") for video in videos):
                raise ValueError("Choose one or more MP4 video clips.")
            self._idle(project_id, repository.state())
            await self.executor.call(f"editor:{project_id}", store)
        finally:
            for video in videos:
                await video.close()
        return self.workspace_view(project_id)

    async def create_workspace(self, name, changes, videos):
        created = self.create_draft(name or None)
        try:
            self.save_workspace(created["id"], changes)
            if videos:
                await self.add_clips(created["id"], videos)
        except BaseException:
            # The only removed folder is this request's new, unpublished workspace.
            import shutil
            folder = self.folder(created["id"])
            if folder.resolve().parent == self.root.resolve():
                shutil.rmtree(folder)
            raise
        return self.workspace_view(created["id"])

    def start_analysis(self, project_id):
        repository = ProjectRepository(self.folder(project_id))
        with repository.locked():
            state = repository.state()
            self._idle(project_id, state)
            if not state.get("assets"):
                raise ValueError("Upload at least one clip before analyzing.")
            if (repository.view()["analysis_current"]
                    and state.get("analysis_segmentation_version") == SEGMENTATION_VERSION):
                return {"status": "analyzed"}
            repository.update(**preserve_baseline(repository, state), status="analyzing", error=None,
                              message="Analyzing clips...", progress=0)
            try:
                if not self._schedule(repository.folder, analysis.analyze_project):
                    raise RuntimeError("Analysis is already running.")
            except Exception:
                repository.update(status=state["status"])
                raise
        return {"status": "analyzing"}

    def workspace_view(self, project_id):
        repository = ProjectRepository(self.folder(project_id))
        with repository.locked():
            state = repository.view()
            state["analysis_upgrade_available"] = (state["has_analysis"]
                and state.get("analysis_segmentation_version") != SEGMENTATION_VERSION)
            analyzed = set()
            if state["has_analysis"]:
                analyzed = set(repository.read_artifact("private-source-map.json")["assets"])
            state["assets"] = [{**asset, "analyzed": asset["id"] in analyzed} for asset in state.get("assets", [])]
            video = state.get("last_video")
            if not video and state.get("output_file"):
                video = {"file": state["output_file"], "plan_revision": state.get("plan_revision", ""),
                         "signature": state.get("analysis_signature", signature(state)),
                         "script": state.get("resolved", {}).get("script", "")}
            state["video"] = {**video, "previous": not state["plan_current"] or video.get("signature") != signature(state)
                              or video.get("plan_revision") != state.get("plan_revision")} if video else None
            return state
