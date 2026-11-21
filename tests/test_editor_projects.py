"""Named-project creation and upload integration without running the ML pipeline."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch

from pyscenedetect_demo.editor.project_names import DuplicateProjectName
from pyscenedetect_demo.storage import ProjectRepository
from pyscenedetect_demo.web import create_app
from tests.http_client import multipart, request


class NamedProjectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(output_root=str(self.root))
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.service = self.app.state.editor_service

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.temporary.cleanup()

    async def draft(self, name):
        return await request(
            self.app, "/api/editor/projects/draft", method="POST",
            body=urlencode({"name": name}).encode(),
            headers=[(b"content-type", b"application/x-www-form-urlencoded")],
        )

    async def test_draft_is_persisted_and_duplicate_names_do_not_replace_it(self):
        status, _, body = await self.draft("Project_1")
        self.assertEqual(status, 200, body)
        created = json.loads(body)
        self.assertRegex(created["id"], r"^[a-f0-9]{32}$")
        state = self.service.view(created["id"])
        self.assertEqual(state["name"], "Project_1")
        self.assertEqual(state["status"], "draft")
        self.assertFalse(state["has_analysis"])
        before = ProjectRepository(self.service.folder(created["id"])).state()
        for name in ("project_1", "  PROJECT_1  ", "Ｐｒｏｊｅｃｔ＿１"):
            status, _, body = await self.draft(name)
            self.assertEqual(status, 409, body)
        self.assertEqual(ProjectRepository(self.service.folder(created["id"])).state(), before)
        self.assertEqual(self.service.create_draft()["name"], "Project_2")
        self.assertEqual(len(self.service.list_projects()), 2)

    async def test_invalid_names_are_rejected_without_creating_projects(self):
        for name in ("", "   ", "x" * 81):
            status, _, body = await self.draft(name)
            self.assertEqual(status, 400, body)
        self.assertEqual(self.service.list_projects(), [])

    async def test_delete_removes_only_selected_project_and_its_generated_files(self):
        first = self.service.create_draft("Delete me")
        second = self.service.create_draft("Keep me")
        folder = self.service.folder(first["id"])
        other = self.service.folder(second["id"])
        original = self.root / "original.mp4"
        original.write_bytes(b"original upload outside project")
        for name in ("media/clip.mp4", ".analysis/revision/analysis.json", "renders/revision/edited.mp4"):
            artifact = folder / name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(b"project artifact")
        status, _, body = await request(self.app, f'/api/editor/projects/{first["id"]}', method="DELETE")
        self.assertEqual(status, 204, body)
        self.assertEqual(body, b"")
        self.assertFalse(folder.exists())
        self.assertTrue((other / "project.json").is_file())
        self.assertEqual(original.read_bytes(), b"original upload outside project")
        self.assertEqual([p["id"] for p in self.service.list_projects()], [second["id"]])
        self.assertEqual((await request(self.app, f'/api/editor/projects/{first["id"]}'))[0], 404)
        self.assertEqual((await request(self.app, f'/api/editor/projects/{first["id"]}', method="DELETE"))[0], 404)
        self.assertEqual(self.service.create_draft("Delete me")["name"], "Delete me")

    async def test_delete_rejects_processing_or_queued_projects(self):
        project = self.service.create_draft("Busy")
        folder = self.service.folder(project["id"])
        repository = ProjectRepository(folder)
        for state in ("analyzing", "rendering"):
            repository.update(status=state)
            status, _, _ = await request(self.app, f'/api/editor/projects/{project["id"]}', method="DELETE")
            self.assertEqual(status, 409)
            self.assertTrue((folder / "project.json").is_file())
        repository.update(status="draft")
        with patch.object(self.service.executor, "contains", return_value=True):
            status, _, _ = await request(self.app, f'/api/editor/projects/{project["id"]}', method="DELETE")
        self.assertEqual(status, 409)
        self.assertTrue(folder.is_dir())

    async def test_delete_checks_project_directory_and_reports_files_in_use(self):
        project = self.service.create_draft("Keep safe")
        folder = self.service.folder(project["id"])
        with patch.object(self.service, "folder", return_value=self.root):
            status, _, _ = await request(self.app, f'/api/editor/projects/{project["id"]}', method="DELETE")
        self.assertEqual(status, 400)
        self.assertTrue(folder.is_dir())
        for identifier in ("invalid", "0" * 32):
            status, _, _ = await request(self.app, f'/api/editor/projects/{identifier}', method="DELETE")
            self.assertEqual(status, 404)
        with patch("pyscenedetect_demo.services.editor.shutil.rmtree", side_effect=PermissionError("In use")):
            status, _, body = await request(self.app, f'/api/editor/projects/{project["id"]}', method="DELETE")
        self.assertEqual(status, 409)
        self.assertIn(b"try again", body)
        self.assertTrue((folder / "project.json").is_file())

    async def test_concurrent_creations_reserve_unique_names(self):
        def reserve(_):
            try:
                return self.service.create_draft("My video")
            except DuplicateProjectName:
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(reserve, range(4)))
            defaults = list(pool.map(lambda _: self.service.create_draft(), range(4)))
        self.assertEqual(sum(item is not None for item in results), 1)
        self.assertEqual({item["name"] for item in defaults}, {f"Project_{i}" for i in range(1, 5)})

    async def test_upload_uses_the_named_draft_and_cannot_overwrite_analyzed_work(self):
        created = self.service.create_draft("My video")
        body, headers = multipart(
            {"project_id": created["id"], "topic": "My topic"}, [("videos", "clip.mp4", b"first upload")]
        )
        with patch.object(self.service, "_schedule") as schedule:
            status, _, content = await request(self.app, "/api/editor/projects", method="POST", body=body, headers=headers)
        self.assertEqual(status, 200, content)
        self.assertEqual(json.loads(content)["id"], created["id"])
        schedule.assert_called_once()
        folder = self.service.folder(created["id"])
        state = ProjectRepository(folder).state()
        self.assertEqual(state["name"], "My video")
        self.assertEqual(state["topic"], "My topic")
        ProjectRepository(folder).update(status="analyzed")
        status, _, _ = await request(self.app, "/api/editor/projects", method="POST", body=body, headers=headers)
        self.assertEqual(status, 409)
        self.assertEqual((folder / "media/asset_0001.mp4").read_bytes(), b"first upload")
        self.assertEqual(len(self.service.list_projects()), 1)

    async def test_failed_upload_leaves_the_draft_available_for_retry(self):
        created = self.service.create_draft("Retry me")
        for filename, content in (("clip.mov", b"unsupported"), ("clip.mp4", b"")):
            body, headers = multipart({"project_id": created["id"]}, [("videos", filename, content)])
            status, _, response = await request(self.app, "/api/editor/projects", method="POST", body=body, headers=headers)
            self.assertEqual(status, 400, response)
            state = self.service.view(created["id"])
            self.assertEqual(state["status"], "draft")
            self.assertEqual(state["assets"], [])
            self.assertEqual(state["name"], "Retry me")

    async def test_legacy_upload_still_creates_a_project_with_a_unique_readable_name(self):
        self.service.create_draft("Project_1")
        body, headers = multipart({}, [("videos", "clip.mp4", b"fixture")])
        with patch.object(self.service, "_schedule"):
            status, _, content = await request(self.app, "/api/editor/projects", method="POST", body=body, headers=headers)
        self.assertEqual(status, 200, content)
        state = self.service.view(json.loads(content)["id"])
        self.assertEqual(state["name"], "Project_2")
