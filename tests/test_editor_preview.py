"""Real media and HTTP regression checks for sound in embedded previews."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pyscenedetect_demo.editor.preview import browser_preview
from pyscenedetect_demo.media import run_command
from pyscenedetect_demo.storage import ProjectRepository
from pyscenedetect_demo.web import create_app
from tests.http_client import request


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are not installed")
class PreviewTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.app = create_app(output_root=self.temporary.name)
        self.lifespan = self.app.router.lifespan_context(self.app)
        await self.lifespan.__aenter__()
        self.service = self.app.state.editor_service
        self.identifier = self.service.create_draft("Preview test")["id"]
        self.folder = self.service.folder(self.identifier)
        self.source = self.folder / "renders/revision/render/edited.mp4"
        self.source.parent.mkdir(parents=True)
        run_command([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=30:d=0.5",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(self.source),
        ])
        ProjectRepository(self.folder).update(last_video={"file": str(self.source.relative_to(self.folder))})
        self.url = f"/api/editor/projects/{self.identifier}/video"

    async def asyncTearDown(self):
        await self.lifespan.__aexit__(None, None, None)

    async def test_preview_has_audible_mp3_audio_and_unchanged_picture_and_export(self):
        original = self.source.read_bytes()
        status, headers, body = await request(self.app, self.url + "?preview=true")
        self.assertEqual(status, 200, body[:200])
        self.assertEqual(headers[b"content-type"], b"video/mp4")
        self.assertNotIn(b"content-disposition", headers)
        preview = self.source.with_name("edited.preview.mp4")
        self.assertEqual(body, preview.read_bytes())
        streams = json.loads(run_command([
            "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(preview),
        ]))["streams"]
        self.assertEqual([s["codec_name"] for s in streams], ["h264", "mp3"])
        self.assertLess(abs(float(streams[0]["duration"]) - float(streams[1]["duration"])), 0.05)
        audio = subprocess.run([
            "ffmpeg", "-v", "error", "-i", str(preview), "-map", "0:a:0",
            "-f", "s16le", "-acodec", "pcm_s16le", "-",
        ], capture_output=True, check=True).stdout
        self.assertGreater(max(abs(int.from_bytes(audio[i:i+2], "little", signed=True))
                               for i in range(0, len(audio), 2)), 1000)
        for path in (self.source, preview):
            picture = run_command([
                "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-c:v", "copy",
                "-f", "hash", "-hash", "sha256", "-",
            ])
            if path == self.source:
                original_picture = picture
            else:
                self.assertEqual(picture, original_picture)
        with patch("pyscenedetect_demo.editor.preview.run_command", side_effect=AssertionError("Cache missed")):
            self.assertEqual(browser_preview(self.source), preview)
            status, range_headers, chunk = await request(
                self.app, self.url + "?preview=true", headers=[(b"range", b"bytes=0-127")],
            )
        self.assertEqual(status, 206)
        self.assertEqual(chunk, body[:128])
        self.assertEqual(range_headers[b"accept-ranges"], b"bytes")
        for query in ("", "?download=true", "?download=true&preview=true"):
            status, headers, content = await request(self.app, self.url + query)
            self.assertEqual(status, 200)
            self.assertEqual(content, original)
            if "download=true" in query:
                self.assertIn(b"attachment", headers[b"content-disposition"])
        self.assertEqual(self.source.read_bytes(), original)

    async def test_failed_preview_leaves_export_available_and_cleans_partial_file(self):
        def fail(command):
            Path(command[-1]).write_bytes(b"incomplete")
            raise ValueError("Encoder failed")

        with patch("pyscenedetect_demo.editor.preview.run_command", side_effect=fail):
            status, _, _ = await request(self.app, self.url + "?preview=true")
        self.assertEqual(status, 503)
        self.assertEqual(list(self.source.parent.iterdir()), [self.source])
        status, _, content = await request(self.app, self.url + "?download=true")
        self.assertEqual(status, 200)
        self.assertEqual(content, self.source.read_bytes())

    async def test_preview_cannot_read_outside_project(self):
        ProjectRepository(self.folder).update(last_video={"file": "../outside.mp4"})
        with patch("pyscenedetect_demo.web.edit_routes.browser_preview") as encode:
            status, _, _ = await request(self.app, self.url + "?preview=true")
        self.assertEqual(status, 404)
        encode.assert_not_called()
