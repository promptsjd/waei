"""Real FFmpeg checks use generated media and never touch live app output."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import warnings
from pathlib import Path

from pyscenedetect_demo.editor.plans import accept_plan
from pyscenedetect_demo.editor.rendering import render_project
from pyscenedetect_demo.media import file_hash, probe, run_command
from pyscenedetect_demo.pipeline import run_scene_detection
from pyscenedetect_demo.scene_context import analyze_scene_context
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.shotlist import run_shotlist, regenerate_shotlist
from pyscenedetect_demo.storage import ProjectRepository, write_json


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are not installed")
class MediaRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="scene-media-checks-")
        cls.root = Path(cls.temporary.name)
        cls.video = cls.root / "three-scenes.mp4"
        run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=red:s=160x90:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=160x90:r=30:d=1",
                "-f",
                "lavfi",
                "-i",
                "color=c=green:s=160x90:r=30:d=1",
                "-filter_complex",
                "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map",
                "[v]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(cls.video),
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_analysis_shotlist_and_minimal_editor_context_agree_on_boundaries(self):
        analysis = run_scene_detection(
            video_path=self.video,
            output_root=self.root / "analysis",
            detector_name="content",
            threshold=27.0,
            min_scene_len_seconds=0.8,
            frame_mode="middle",
            transcribe=False,
            asr_model_name="tiny",
            language=None,
            describe_visuals=False,
            vision_model_name="microsoft/Florence-2-base",
            show_progress=False,
        )
        self.assertEqual(
            [(scene["start_frame"], scene["end_frame"]) for scene in analysis["scenes"]],
            [(0, 30), (30, 60), (60, 90)],
        )
        self.assertTrue(Path(analysis["summary"]["html_path"]).is_file())
        self.assertTrue(Path(analysis["summary"]["csv_path"]).is_file())
        self.assertTrue(all(not scene["audio_path"] for scene in analysis["scenes"]))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            shots = run_shotlist(
                video_path=self.video,
                output_root=self.root / "shotlist",
                detector_name="content",
                threshold=27.0,
                min_scene_len_seconds=0.8,
                show_progress=False,
            )
        self.assertEqual(
            [(shot["start_frame"], shot["end_frame"]) for shot in shots["shots"]],
            [(0, 29), (30, 59), (60, 89)],
        )
        self.assertTrue(regenerate_shotlist(json_path=Path(shots["summary"]["json_path"])).is_file())
        context_dir = self.root / "context"
        scenes = analyze_scene_context(
            self.video, context_dir, settings=AppSettings(), describe_visuals=False
        )
        self.assertEqual(
            [(scene["start_seconds"], scene["end_seconds"]) for scene in scenes], [(0, 1), (1, 2), (2, 3)]
        )
        self.assertFalse(
            context_dir.exists(), "Editor context must not generate unused reports, frames or audio"
        )

    def test_renderer_preserves_linked_audio_and_handles_silent_portrait_clip(self):
        folder = self.root / "render-project"
        media = folder / "media"
        media.mkdir(parents=True, exist_ok=True)
        first = media / "asset_0001.mp4"
        second = media / "asset_0002.mp4"
        run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(self.video),
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=3",
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-shortest",
                str(first),
            ]
        )
        run_command(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=90x160:r=24:d=1.5",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(second),
            ]
        )
        assets = [
            {"id": identifier, "sha256": file_hash(path), **probe(path)}
            for identifier, path in [("asset_0001", first), ("asset_0002", second)]
        ]
        analysis = {
            "version": "2.0",
            "input_id": "render-test",
            "analysis_complete": True,
            "duration_ms": 4500,
            "allow_reorder": False,
            "required_unit_ids": [],
            "units": [],
        }
        for identifier, start, end in [("u1", 0, 3000), ("u2", 3000, 4500)]:
            analysis["units"].append(
                {
                    "id": identifier,
                    "start_ms": start,
                    "end_ms": end,
                    "kind": "silence",
                    "text": "",
                    "speaker": None,
                    "speech_confidence": None,
                    "boundary_quality": "candidate",
                    "visual_description": None,
                }
            )
        mapping = {
            "version": "2.0",
            "input_id": "render-test",
            "assets": {"asset_0001": {"duration_ms": 3000}, "asset_0002": {"duration_ms": 1500}},
            "units": {
                "u1": {"asset_id": "asset_0001", "in_ms": 0, "out_ms": 3000},
                "u2": {"asset_id": "asset_0002", "in_ms": 0, "out_ms": 1500},
            },
        }
        write_json(folder / "project.json", {"status": "analyzed", "assets": assets})
        write_json(folder / "analysis.json", analysis)
        write_json(folder / "private-source-map.json", mapping)
        plan = {
            "version": "2.0",
            "input_id": "render-test",
            "sequence": [{"unit_ids": ["u1", "u2"]}],
            "removed_unit_ids": [],
        }
        accepted = accept_plan(folder, json.dumps(plan))
        render_project(folder)
        state = ProjectRepository(folder).state()
        output = folder / state["output_file"]
        details = probe(output)
        self.assertEqual(state["status"], "completed")
        self.assertTrue(state["render_is_preview"])
        self.assertTrue(details["has_audio"])
        self.assertEqual((details["width"], details["height"]), (160, 90))
        self.assertLessEqual(abs(details["duration_ms"] - accepted["duration_ms"]), 150)
        streams = json.loads(
            run_command(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(output)])
        )["streams"]
        by_type = {stream["codec_type"]: stream for stream in streams}
        self.assertEqual(by_type["video"]["avg_frame_rate"], "30/1")
        self.assertLess(abs(float(by_type["video"]["duration"]) - float(by_type["audio"]["duration"])), 0.15)
        run_command(["ffmpeg", "-v", "error", "-i", str(output), "-f", "null", "-"])
        # A source change must still invalidate rendering even after storage refactoring.
        with first.open("ab") as handle:
            handle.write(b"changed")
        with self.assertRaisesRegex(ValueError, "source has changed"):
            render_project(folder)
