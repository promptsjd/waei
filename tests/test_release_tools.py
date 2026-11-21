"""Source exports must exclude user data, remain reproducible and never overwrite."""

import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools import codespace, prepare_release


class SourceExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.root.mkdir()
        for name in prepare_release.ROOT_FILES:
            (self.root / name).write_text("source fixture\n", encoding="utf-8")
        for name in ["src/app.py", "tests/fixture.json", ".github/workflows/checks.yml", ".devcontainer/Dockerfile",
                     ".git/config", "output/private.json", "models/weights.bin", ".env", ".codex",
                     "src/__pycache__/app.pyc", "src/app.egg-info/PKG-INFO", "tests/private.mp4"]:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fixture\n", encoding="utf-8")
        self.destination = self.root / "release" / "waie-source"

    def test_export_contains_source_and_verified_manifest_but_no_local_data(self):
        archive, count = prepare_release.export(self.root, self.destination)
        manifest = json.loads((self.destination / "SOURCE_MANIFEST.json").read_text())
        self.assertEqual(count, len(manifest["files"]))
        for name, digest in manifest["files"].items():
            self.assertEqual(hashlib.sha256((self.destination / name).read_bytes()).hexdigest(), digest)
        for name in ["src/app.py", ".github/workflows/checks.yml", ".devcontainer/Dockerfile"]:
            self.assertIn(name, manifest["files"])
        for name in [".git/config", "output/private.json", "models/weights.bin", ".env", ".codex",
                     "src/__pycache__/app.pyc", "src/app.egg-info/PKG-INFO", "tests/private.mp4"]:
            self.assertFalse((self.destination / name).exists(), name)
        with zipfile.ZipFile(archive) as package:
            self.assertEqual(len(package.namelist()), count + 1)
            self.assertTrue(all(name.startswith("waie-source/") for name in package.namelist()))

    def test_existing_exports_and_source_tree_destinations_are_rejected(self):
        prepare_release.export(self.root, self.destination)
        with self.assertRaises(FileExistsError):
            prepare_release.export(self.root, self.destination)
        with self.assertRaises(ValueError):
            prepare_release.export(self.root, self.root / "src/export")


class CodespaceStarterTests(unittest.TestCase):
    def test_fresh_server_starts_privately_and_can_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            processes = []
            launch = subprocess.Popen

            def capture(*args, **kwargs):
                process = launch(*args, **kwargs)
                processes.append(process)
                self.assertEqual(kwargs["env"]["SCENE_SCRIBE_HOST"], "127.0.0.1")
                return process

            try:
                # Own the actual interpreter directly, avoiding the extra child
                # created by Windows venv launcher executables.
                interpreter = Path(getattr(sys, "_base_executable", sys.executable))
                with patch.dict(os.environ, {"PYTHONPATH": os.pathsep.join(filter(None, sys.path))}), \
                        patch.object(codespace, "python_path", return_value=interpreter):
                    with patch.object(codespace.subprocess, "Popen", side_effect=capture):
                        codespace.start(root, port)
                    self.assertEqual(len(processes), 1)
                    codespace.start(root, port)
                    self.assertIsNone(processes[0].poll())
                    self.assertEqual(codespace.health(f"http://127.0.0.1:{port}")["output_root"],
                                     str((root / "output").resolve()))
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=10)

    def test_matching_server_is_reused_without_starting_another_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python"
            python.touch()
            state = {"application": "scene-scribe", "output_root": str((root / "output").resolve()),
                     "revision": "current"}
            with patch.object(codespace, "python_path", return_value=python), \
                    patch.object(codespace, "health", return_value=state), \
                    patch.object(codespace.subprocess, "check_output", return_value="current\n"), \
                    patch.object(codespace.subprocess, "Popen") as spawn:
                codespace.start(root)
                spawn.assert_not_called()

    def test_foreign_or_outdated_server_is_never_stopped_or_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "python"
            python.touch()
            for state in [{"application": "other"},
                          {"application": "scene-scribe", "output_root": str((root / "output").resolve()),
                           "revision": "old"}]:
                with self.subTest(state=state), \
                        patch.object(codespace, "python_path", return_value=python), \
                        patch.object(codespace, "health", return_value=state), \
                        patch.object(codespace.subprocess, "check_output", return_value="current\n"), \
                        patch.object(codespace.subprocess, "Popen") as spawn:
                    with self.assertRaisesRegex(RuntimeError, "another or outdated server"):
                        codespace.start(root)
                    spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
