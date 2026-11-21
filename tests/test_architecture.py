from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pyscenedetect_demo import contract
from pyscenedetect_demo.editor.plans import accept_plan
from pyscenedetect_demo.editor.segmentation import build_units
from pyscenedetect_demo.execution import BackgroundExecutor, EventHub
from pyscenedetect_demo.progress import ProgressTracker
from pyscenedetect_demo.repositories.jobs import JobManager
from pyscenedetect_demo.services.jobs import JobService
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.storage import ProjectRepository, read_json, write_json
from pyscenedetect_demo.web import create_app
from tests.http_client import request, multipart


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_segmentation_preserves_recorded_words_and_full_source_coverage(self):
        fixture = read_json(Path(__file__).parent / "fixtures/segmentation-baseline.json")
        units = build_units(fixture["words"], fixture["duration_ms"])
        self.assertEqual(" ".join(unit["text"] for unit in units if unit["text"]),
                         " ".join(word["word"].strip() for word in fixture["words"]))
        self.assertEqual(units[0]["start_ms"], 0)
        self.assertEqual(units[-1]["end_ms"], fixture["duration_ms"])
        for left, right in zip(units, units[1:]):
            self.assertEqual(left["end_ms"], right["start_ms"])

    def test_job_snapshots_cannot_mutate_the_repository(self):
        manager = JobManager(self.root, self.root)
        config = {"nested": {"enabled": True}}
        identifier = manager.create_job(
            video_name="clip.mp4", video_path=self.root / "clip.mp4", config=config
        )
        config["nested"]["enabled"] = False
        manager.get_job(identifier)["config"]["nested"]["enabled"] = False
        manager.list_jobs()[0]["status"] = "failed"
        self.assertTrue(manager.get_job(identifier)["config"]["nested"]["enabled"])
        self.assertEqual(manager.get_job(identifier)["status"], "pending")

    def test_corrupt_database_is_preserved_and_last_good_state_recovers(self):
        manager = JobManager(self.root, self.root)
        identifier = manager.create_job(video_name="clip.mp4", video_path=self.root / "clip.mp4", config={})
        manager.save()
        damaged = self.root / "web_jobs.json"
        damaged.write_bytes(b"{interrupted-write")
        recovered = JobManager(self.root, self.root)
        with self.assertLogs("pyscenedetect_demo.repositories.jobs", level="WARNING"):
            recovered.load()
        self.assertIsNotNone(recovered.get_job(identifier))
        copies = list(self.root.glob("web_jobs.json.corrupt-*"))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), b"{interrupted-write")

    def test_failed_atomic_write_preserves_existing_database(self):
        manager = JobManager(self.root, self.root)
        manager.create_job(video_name="clip.mp4", video_path=self.root / "clip.mp4", config={})
        previous = (self.root / "web_jobs.json").read_bytes()
        with patch("pyscenedetect_demo.storage.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                manager.save()
        self.assertEqual((self.root / "web_jobs.json").read_bytes(), previous)

    def test_failed_job_update_rolls_back_memory_as_well_as_disk(self):
        manager = JobManager(self.root, self.root)
        identifier = manager.create_job(video_name="clip.mp4", video_path=self.root / "clip.mp4", config={})
        with patch("pyscenedetect_demo.storage.os.fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                manager.update_job(identifier, {"status": "running"})
        self.assertEqual(manager.get_job(identifier)["status"], "pending")
        self.assertEqual(read_json(self.root / "web_jobs.json")["jobs"][identifier]["status"], "pending")

    def test_failed_plan_commit_keeps_previous_revision_visible(self):
        for source, target in [
            ("llm-input.json", "analysis.json"),
            ("private-source-map.json", "private-source-map.json"),
        ]:
            write_json(self.root / target, contract.read_json(contract.RESOURCES / "examples" / source))
        write_json(self.root / "project.json", {"status": "analyzed"})
        plan = contract.read_json(contract.RESOURCES / "examples/llm-edit-plan.json")
        accept_plan(self.root, json.dumps(plan))
        repository = ProjectRepository(self.root)
        previous = repository.state()
        changed = copy.deepcopy(plan)
        changed["sequence"] = [{"unit_ids": [uid]} for run in plan["sequence"] for uid in run["unit_ids"]]
        from pyscenedetect_demo import storage

        actual_write = storage.write_json

        def fail_at_commit(path, value):
            if Path(path).name == "project.json":
                raise OSError("interrupted before publication")
            actual_write(path, value)

        with patch.object(storage, "write_json", side_effect=fail_at_commit):
            with self.assertRaises(OSError):
                accept_plan(self.root, json.dumps(changed))
        self.assertEqual(repository.state(), previous)
        self.assertEqual(repository.read_artifact("plan.json"), plan)
        self.assertEqual(read_json(self.root / "plan.json"), plan)

    def test_concurrent_project_updates_do_not_lose_fields(self):
        write_json(self.root / "project.json", {"status": "analyzed"})
        barrier = threading.Barrier(8)

        def update(index):
            barrier.wait()
            ProjectRepository(self.root).update(**{f"field_{index}": index})

        workers = [threading.Thread(target=update, args=(index,)) for index in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(len(ProjectRepository(self.root).state()), 9)


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_awaited_work_propagates_errors_and_survives_caller_cancellation(self):
        executor = BackgroundExecutor()

        async def failing():
            raise OSError("fixture storage failure")

        with self.assertRaisesRegex(OSError, "fixture storage failure"):
            await executor.call("failure", failing)
        started, release, completed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def operation():
            started.set()
            await release.wait()
            completed.set()

        caller = asyncio.create_task(executor.call("disconnect", operation))
        await started.wait()
        caller.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await caller
        self.assertTrue(executor.contains("disconnect"))
        release.set()
        await executor.close()
        self.assertTrue(completed.is_set())

    async def test_all_features_share_limit_and_duplicate_keys_are_rejected(self):
        executor = BackgroundExecutor(1)
        release = asyncio.Event()
        first_started = asyncio.Event()
        order = []

        async def analysis():
            order.append("analysis")
            first_started.set()
            await release.wait()

        async def editor():
            order.append("editor")

        self.assertTrue(executor.submit("job:a", analysis))
        self.assertFalse(executor.submit("job:a", editor))
        self.assertTrue(executor.submit("editor:b", editor))
        await first_started.wait()
        self.assertEqual(order, ["analysis"])
        release.set()
        await executor.close()
        self.assertEqual(order, ["analysis", "editor"])
        self.assertFalse(executor.contains("job:a"))
        with self.assertRaises(RuntimeError):
            executor.submit("after-close", editor)

    async def test_subscribers_receive_independent_terminal_events(self):
        hub = EventHub()
        first, second = hub.subscribe("job"), hub.subscribe("job")
        hub.publish("job", {"event": "complete", "data": "{}"})
        self.assertEqual((await first.get())["event"], "complete")
        self.assertEqual((await second.get())["event"], "complete")
        hub.unsubscribe("job", first)
        for index in range(200):
            hub.publish("job", {"event": "progress", "data": str(index)})
        hub.publish("job", {"event": "failed", "data": "{}"})
        remaining = [second.get_nowait() for _ in range(second.qsize())]
        self.assertEqual(remaining[-1]["event"], "failed")
        self.assertLessEqual(len(remaining), 128)
        hub.unsubscribe("job", second)
        self.assertFalse(hub._subscribers)

    async def test_failure_releases_execution_slot_for_next_feature(self):
        executor = BackgroundExecutor()
        reached = asyncio.Event()

        async def failing():
            raise ValueError("fixture failure")

        async def succeeding():
            reached.set()

        with self.assertLogs("pyscenedetect_demo.execution", level="ERROR"):
            executor.submit("bad", failing)
            executor.submit("good", succeeding)
            await executor.close()
        self.assertTrue(reached.is_set())

    async def test_analysis_service_serializes_jobs_and_rejects_delete_while_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = JobManager(root, root)
            executor = BackgroundExecutor()
            active = 0
            maximum = 0
            lock = threading.Lock()
            release = threading.Event()
            started = asyncio.Event()
            loop = asyncio.get_running_loop()

            def analyze(**options):
                nonlocal active, maximum
                with lock:
                    active += 1
                    maximum = max(maximum, active)
                loop.call_soon_threadsafe(started.set)
                release.wait(timeout=5)
                with lock:
                    active -= 1
                return {"summary": {"scene_count": 3, "output_dir": str(root / "output")}}

            service = JobService(manager, executor, AppSettings(), analyzer=analyze)
            identifiers = [
                manager.create_job(video_name="clip.mp4", video_path=root / "clip.mp4", config={})
                for _ in range(2)
            ]
            for identifier in identifiers:
                self.assertTrue(service.start(identifier))
                self.assertFalse(service.start(identifier))
            with self.assertRaises(ValueError):
                service.delete(identifiers[1])
            await asyncio.wait_for(started.wait(), timeout=2)
            self.assertEqual(manager.get_job(identifiers[0])["status"], "running")
            self.assertEqual(manager.get_job(identifiers[1])["status"], "pending")
            release.set()
            await executor.close()
            self.assertEqual(maximum, 1)
            self.assertTrue(
                all(manager.get_job(identifier)["status"] == "completed" for identifier in identifiers)
            )


class HttpIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_reports_loaded_revision_even_when_source_changes(self):
        loaded_revision = self.app.state.source_revision
        with patch("pyscenedetect_demo.runtime.source_revision", return_value="changed-on-disk"):
            status, _, content = await request(self.app, "/api/health")
        self.assertEqual(status, 200)
        state = json.loads(content)
        self.assertEqual(state["application"], "scene-scribe")
        self.assertEqual(state["revision"], loaded_revision)
        self.assertEqual(state["output_root"], str(self.root.resolve()))

    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.app = create_app(output_root=str(self.root))
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)
        self.temporary.cleanup()

    async def test_original_and_editor_pages_and_static_assets_remain_available(self):
        for path in ("/", "/editor", "/static/js/app.js", "/static/js/editor.js", "/static/js/job-detail.js"):
            with self.subTest(path=path):
                status, _, body = await request(self.app, path)
                self.assertEqual(status, 200, body)
        self.assertIn(b'value="27.0"', (await request(self.app, "/"))[2])
        self.assertIn("WAIE \u00b7 Home".encode(), (await request(self.app, "/"))[2])
        self.assertIn(" \u2192 ".encode(), (await request(self.app, "/static/js/job-detail.js"))[2])

    async def test_windows_output_download_and_escape_protection(self):
        manager = self.app.state.job_manager
        output = self.root / "result"
        output.mkdir()
        (output / "report.html").write_text("fixture report")
        (self.root / "outside.txt").write_text("must stay private")
        identifier = manager.create_job(video_name="clip.mp4", video_path=self.root / "clip.mp4", config={})
        manager.update_job(identifier, {"status": "completed", "output_dir": str(output)})
        status, _, body = await request(self.app, f"/api/jobs/{identifier}/files/report.html")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"fixture report")
        status, _, _ = await request(self.app, f"/api/jobs/{identifier}/files/../outside.txt")
        self.assertEqual(status, 403)

    async def test_upload_and_job_response_contract_is_preserved(self):
        def analyze(**options):
            return {"summary": {"scene_count": 3, "output_dir": str(self.root / "result")}}

        self.app.state.job_service.analyzer = analyze
        body, headers = multipart({"mode": "analyze"}, [("video", "clip.mp4", b"fixture")])
        status, _, content = await request(self.app, "/api/jobs", method="POST", body=body, headers=headers)
        self.assertEqual(status, 200, content)
        created = json.loads(content)
        self.assertEqual(set(created), {"job_id", "status"})
        self.assertEqual(created["status"], "pending")
        await self.app.state.executor.close()
        status, _, content = await request(self.app, f"/api/jobs/{created['job_id']}")
        self.assertEqual(json.loads(content)["status"], "completed")

    async def test_invalid_configuration_does_not_create_a_job(self):
        for threshold in ("nan", "-1"):
            body, headers = multipart({"threshold": threshold}, [("video", "clip.mp4", b"fixture")])
            status, _, _ = await request(self.app, "/api/jobs", method="POST", body=body, headers=headers)
            self.assertIn(status, (400, 422))
        self.assertEqual(self.app.state.job_manager.list_jobs(), [])

    async def test_injected_detection_defaults_reach_both_ui_and_processing(self):
        settings = replace(
            AppSettings(),
            output_root=self.root / "custom",
            detection=replace(AppSettings().detection, threshold=42.0),
        )
        app = create_app(settings=settings)
        observed = []

        def analyzer(**options):
            observed.append(options["threshold"])
            return {"summary": {"scene_count": 1, "output_dir": str(settings.output_root / "result")}}

        async with app.router.lifespan_context(app):
            app.state.job_service.analyzer = analyzer
            self.assertIn(b'value="42.0"', (await request(app, "/"))[2])
            body, headers = multipart({}, [("video", "clip.mp4", b"fixture")])
            self.assertEqual(
                (await request(app, "/api/jobs", method="POST", body=body, headers=headers))[0], 200
            )
            await app.state.executor.close()
        self.assertEqual(observed, [42.0])

    async def test_editor_disabled_does_not_disable_analysis(self):
        app = create_app(
            settings=replace(AppSettings(), output_root=self.root / "separate", enable_editor=False)
        )
        async with app.router.lifespan_context(app):
            self.assertEqual((await request(app, "/"))[0], 200)
            self.assertEqual((await request(app, "/editor"))[0], 404)

    async def test_legacy_project_plan_and_download_still_work(self):
        identifier = "a" * 32
        folder = self.root / "editor" / identifier
        folder.mkdir(parents=True)
        for source, target in [
            ("llm-input.json", "analysis.json"),
            ("private-source-map.json", "private-source-map.json"),
        ]:
            write_json(folder / target, contract.read_json(contract.RESOURCES / "examples/v1" / source))
        write_json(
            folder / "project.json",
            {"id": identifier, "status": "analyzed", "brief": {}, "created_at": "2026-01-01"},
        )
        plan = contract.read_json(contract.RESOURCES / "examples/v1/llm-edit-plan.json")
        status, _, content = await request(
            self.app, f"/api/editor/projects/{identifier}/plan", method="POST", body=json.dumps(plan).encode()
        )
        self.assertEqual(status, 200, content)
        status, _, content = await request(self.app, f"/api/editor/projects/{identifier}/download/plan.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content), plan)
        self.assertEqual((await request(self.app, f"/api/editor/projects/{identifier}/prompt"))[0], 200)


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_damaged_editor_project_does_not_break_other_features(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / "editor" / ("b" * 32)
            folder.mkdir(parents=True)
            (folder / "project.json").write_text("{broken")
            app = create_app(output_root=directory)
            with self.assertLogs("pyscenedetect_demo.storage", level="ERROR"):
                async with app.router.lifespan_context(app):
                    self.assertEqual((await request(app, "/"))[0], 200)
                    status, _, content = await request(app, "/api/editor/projects")
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(content), [])
            self.assertEqual((folder / "project.json").read_text(), "{broken")


class ProgressTests(unittest.TestCase):
    def test_optional_stages_and_unknown_stages_do_not_regress_progress(self):
        tracker = ProgressTracker(["detecting", "exporting_frames", "writing_output"])
        values = [
            tracker.event("detecting", 1, 1)["overall_percent"],
            tracker.event("exporting_frames", 1, 2)["overall_percent"],
            tracker.event("future_stage", 1, 1)["overall_percent"],
            tracker.event("writing_output", 1, 1)["overall_percent"],
        ]
        self.assertEqual(values, sorted(values))
        self.assertLess(values[-1], 100)
