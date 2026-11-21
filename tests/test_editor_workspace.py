"""Autosave, incremental analysis, and preservation of earlier project results."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyscenedetect_demo.storage import ProjectRepository, write_json
from pyscenedetect_demo.web import create_app
from tests.http_client import multipart, request


class WorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(output_root=str(self.root))
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.service = self.app.state.editor_service
        self.probe = patch("pyscenedetect_demo.editor.clip_analysis.probe", return_value={
            "duration_ms": 1000, "width": 160, "height": 90, "has_audio": False,
        }).start()
        self.scenes = patch("pyscenedetect_demo.editor.clip_analysis.analyze_scene_context", return_value=[{
            "start_seconds": 0, "end_seconds": 1, "visual_description": "A presenter.",
        }]).start()
        self.addCleanup(patch.stopall)

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.temporary.cleanup()

    async def create(self, changes=None, clips=()):
        body, headers = multipart({"workspace": json.dumps(changes or {})}, clips)
        return await request(self.app, "/api/editor/workspace", method="POST", body=body, headers=headers)

    async def save(self, identifier, **changes):
        return await request(self.app, f"/api/editor/projects/{identifier}/workspace", method="PATCH",
                             body=json.dumps(changes).encode(), headers=[(b"content-type", b"application/json")])

    async def add(self, identifier, content=b"second"):
        body, headers = multipart({}, [("videos", "more.mp4", content)])
        status, _, body = await request(self.app, f"/api/editor/projects/{identifier}/clips", method="POST", body=body, headers=headers)
        self.assertEqual(status, 200, body)
        return json.loads(body)

    async def analyzed(self):
        status, _, body = await self.create({"topic": "Audio"}, [("videos", "first.mp4", b"first")])
        self.assertEqual(status, 200, body)
        identifier = json.loads(body)["id"]
        await self.analyze(identifier)
        self.assertEqual(self.service.view(identifier)["status"], "analyzed", self.service.view(identifier).get("error"))
        return identifier, self.service.view(identifier)

    async def analyze(self, identifier):
        status, _, body = await request(self.app, f"/api/editor/projects/{identifier}/analyze", method="POST")
        self.assertEqual(status, 200, body)

        async def wait():
            while self.app.state.executor.contains(f"editor:{identifier}"):
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait(), timeout=5)

    def plan(self, state):
        return {"version": "2.0", "input_id": state["analysis"]["input_id"],
                "sequence": [{"unit_ids": [unit["id"] for unit in state["analysis"]["units"]]}], "removed_unit_ids": []}

    async def test_explicit_save_can_create_an_empty_draft(self):
        status, _, body = await self.create()
        self.assertEqual(status, 200, body)
        saved = json.loads(body)
        self.assertEqual(saved["name"], "Project_1")
        self.assertEqual(saved["status"], "draft")
        self.assertEqual(saved["assets"], [])

    async def test_content_autosaves_with_same_identity_and_name(self):
        status, _, body = await self.create({"topic": "Audio", "context": "Placement"})
        self.assertEqual(status, 200, body)
        saved = json.loads(body)
        self.assertEqual(saved["name"], "Project_1")
        status, _, body = await self.save(saved["id"], context="Room noise", revision=saved["workspace_revision"])
        self.assertEqual(status, 200, body)
        reopened = self.service.view(saved["id"])
        self.assertEqual(reopened["context"], "Room noise")
        self.assertEqual(reopened["name"], "Project_1")
        self.assertEqual(len(self.service.list_projects()), 1)
        self.assertEqual((await self.save(saved["id"], context="Stale edit", revision=0))[0], 409)
        self.assertEqual(self.service.view(saved["id"])["context"], "Room noise")

    async def test_saved_names_are_immutable_and_rejected_rename_changes_nothing(self):
        status, _, body = await self.create({"name": "  My   video  ", "topic": "Audio"})
        self.assertEqual(status, 200, body)
        saved = json.loads(body)
        self.assertEqual(saved["name"], "My video")
        before = ProjectRepository(self.service.folder(saved["id"])).state()
        status, _, body = await self.save(saved["id"], name="Another name", topic="Must not save")
        self.assertEqual(status, 400, body)
        self.assertIn("cannot be changed", json.loads(body)["detail"])
        self.assertEqual(ProjectRepository(self.service.folder(saved["id"])).state(), before)
        self.assertEqual(len(self.service.list_projects()), 1)
        self.assertEqual((await self.save(saved["id"], name="My video", context="Allowed"))[0], 200)
        self.assertEqual(self.service.view(saved["id"])["context"], "Allowed")

    async def test_clips_are_saved_before_analysis_and_only_new_clips_need_processing(self):
        identifier, original = await self.analyzed()
        self.assertTrue(original["analysis_current"])
        self.assertEqual(self.scenes.call_count, 1)
        first_id = original["assets"][0]["id"]
        updated = await self.add(identifier)
        self.assertEqual(len(updated["assets"]), 2)
        self.assertEqual(updated["assets"][0]["id"], first_id)
        self.assertFalse(updated["analysis_current"])
        self.assertEqual((await request(self.app, f"/api/editor/projects/{identifier}/prompt"))[0], 409)
        folder = self.service.folder(identifier)
        self.assertEqual((folder / "media" / f"{first_id}.mp4").read_bytes(), b"first")
        await self.analyze(identifier)
        result = self.service.view(identifier)
        self.assertEqual(self.scenes.call_count, 2)
        self.assertTrue(result["analysis_current"])
        self.assertEqual(result["analysis"]["duration_ms"], 2000)
        self.assertNotEqual(result["analysis"]["input_id"], original["analysis"]["input_id"])
        self.assertTrue(all(asset["analyzed"] for asset in result["assets"]))

    async def test_removing_new_clips_restores_the_original_prompt_without_analysis(self):
        identifier, original = await self.analyzed()
        prompt = self.service.prompt(identifier)
        await self.add(identifier)
        status, _, body = await self.save(identifier, asset_ids=[original["assets"][0]["id"]])
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["analysis_current"])
        self.assertEqual(self.service.prompt(identifier), prompt)
        self.assertEqual(self.scenes.call_count, 1)

    async def test_existing_project_can_upgrade_analysis_without_changing_content(self):
        identifier, original = await self.analyzed()
        repository = ProjectRepository(self.service.folder(identifier))
        repository.update(analysis_segmentation_version=1)
        self.assertTrue(self.service.view(identifier)["analysis_upgrade_available"])
        await self.analyze(identifier)
        self.assertFalse(self.service.view(identifier)["analysis_upgrade_available"])
        self.assertEqual(self.scenes.call_count, 1)
        self.assertEqual(self.service.view(identifier)["assets"], original["assets"])

    async def test_changed_context_rebuilds_prompt_from_cached_clips_and_rejects_old_ai_response(self):
        identifier, original = await self.analyzed()
        old_plan = self.plan(original)
        self.service.apply_plan(identifier, json.dumps(old_plan))
        self.assertTrue(self.service.view(identifier)["ai_response_current"])
        await self.save(identifier, ai_response="", ai_response_input_id=original["analysis"]["input_id"])
        self.assertEqual(self.service.view(identifier)["ai_response"], "")
        await self.save(identifier, context="A new angle")
        self.assertFalse(self.service.view(identifier)["analysis_current"])
        await self.analyze(identifier)
        latest = self.service.view(identifier)
        self.assertEqual(self.scenes.call_count, 1)
        self.assertFalse(latest["plan_current"])
        self.assertFalse(latest["ai_response_current"])
        with self.assertRaises(ValueError):
            self.service.apply_plan(identifier, json.dumps(old_plan))
        status, _, body = await self.save(identifier, ai_response='{"still": "editing"}', ai_response_input_id=latest["analysis"]["input_id"])
        self.assertEqual(status, 200, body)
        self.assertTrue(self.service.view(identifier)["ai_response_current"])
        self.assertEqual(self.service.view(identifier)["ai_response"], '{"still": "editing"}')
        await self.save(identifier, ai_response="", ai_response_input_id=latest["analysis"]["input_id"])
        self.assertEqual(self.service.view(identifier)["ai_response"], "")

    async def test_previous_video_and_analysis_survive_a_failed_update(self):
        identifier, original = await self.analyzed()
        self.service.apply_plan(identifier, json.dumps(self.plan(original)))
        folder = self.service.folder(identifier)
        output = folder / "renders/previous.mp4"
        output.parent.mkdir()
        output.write_bytes(b"previous video")
        ProjectRepository(folder).update(status="completed", output_file="renders/previous.mp4")
        old_storage = ProjectRepository(folder).state()["analysis_storage_id"]
        await self.add(identifier)
        self.scenes.side_effect = ValueError("New clip cannot be analyzed")
        await self.analyze(identifier)
        state = self.service.view(identifier)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["analysis_storage_id"], old_storage)
        self.assertTrue(state["video"]["previous"])
        status, _, body = await request(self.app, f"/api/editor/projects/{identifier}/video")
        self.assertEqual(status, 200, body)
        self.assertEqual(body, b"previous video")
        self.assertEqual(len(state["assets"]), 2)

    async def test_reorder_reuses_analysis_and_duplicate_imports_do_not_duplicate_sources(self):
        identifier, original = await self.analyzed()
        added = await self.add(identifier)
        await self.analyze(identifier)
        status, _, body = await self.save(identifier, asset_ids=[asset["id"] for asset in reversed(added["assets"])])
        self.assertEqual(status, 200, body)
        await self.analyze(identifier)
        self.assertEqual(self.scenes.call_count, 2)
        duplicate = await self.add(identifier, content=b"first")
        self.assertEqual(len(duplicate["assets"]), 2)
        self.assertTrue(duplicate["analysis_current"])

    async def test_atomic_analysis_failure_keeps_the_published_snapshot(self):
        identifier, original = await self.analyzed()
        repository = ProjectRepository(self.service.folder(identifier))
        old_id = repository.state()["analysis_storage_id"]
        await self.add(identifier)
        from pyscenedetect_demo import storage
        original_write = storage.write_json

        def fail(path, value):
            if Path(path).name == "words.json":
                raise OSError("disk full")
            return original_write(path, value)

        with patch("pyscenedetect_demo.storage.write_json", side_effect=fail):
            await self.analyze(identifier)
        self.assertEqual(repository.state()["analysis_storage_id"], old_id)
        self.assertEqual(repository.read_artifact("analysis.json"), original["analysis"])

    async def test_legacy_saved_analysis_is_reused_on_first_clip_addition(self):
        identifier, original = await self.analyzed()
        folder = self.service.folder(identifier)
        repository = ProjectRepository(folder)
        state = repository.state()
        for key in ("analysis_storage_id", "analysis_signature", "analysis_options"):
            state.pop(key, None)
        write_json(folder / "project.json", state)
        for cached in (folder / ".clip-analysis").glob("*.json"):
            cached.unlink()
        await self.add(identifier)
        await self.analyze(identifier)
        self.assertEqual(self.scenes.call_count, 2)
        self.assertTrue(self.service.view(identifier)["analysis_current"])
        self.assertEqual(len(self.service.view(identifier)["assets"]), 2)

    async def test_required_legacy_content_is_mapped_into_the_updated_analysis(self):
        identifier, original = await self.analyzed()
        repository = ProjectRepository(self.service.folder(identifier))
        analysis = repository.read_artifact("analysis.json")
        analysis["required_unit_ids"] = [analysis["units"][0]["id"]]
        write_json(repository.artifact_path("analysis.json"), analysis)
        await self.add(identifier)
        await self.analyze(identifier)
        updated = self.service.view(identifier)
        self.assertEqual(updated["analysis"]["required_unit_ids"], [updated["analysis"]["units"][0]["id"]])
        self.assertEqual(self.scenes.call_count, 2)
