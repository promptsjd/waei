"""Run optional sample/ML HTTP checks on an isolated server and output folder."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vision", action="store_true")
    parser.add_argument("--transcribe", action="store_true")
    parser.add_argument("--editor", action="store_true")
    parser.add_argument("--workspace", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="scene-http-smoke-") as directory:
        output = Path(directory) / "output"
        output.mkdir()
        env = dict(
            os.environ,
            SCENE_SCRIBE_OUTPUT=str(output),
            SCENE_SCRIBE_PORT=str(port),
            SCENE_SCRIBE_HOST="127.0.0.1",
            SCENE_SCRIBE_URL=f"http://127.0.0.1:{port}",
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            CUDA_VISIBLE_DEVICES="-1",
            HF_HOME=str(root / "models/.hf-cache"),
            PYTHONDONTWRITEBYTECODE="1",
            PYTHONPATH=str(root / "src"),
        )
        log_path = Path(directory) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "-B", "-m", "pyscenedetect_demo.web.main"],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError("Isolated server stopped during startup")
                    try:
                        with urlopen(env["SCENE_SCRIBE_URL"], timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise TimeoutError("Isolated server did not start")
                command = [sys.executable, "-B", "smoke_test.py"]
                if args.vision:
                    command += ["--vision"]
                if args.transcribe:
                    command += ["--transcribe"]
                subprocess.run(command, cwd=root, env=env, check=True)
                if args.editor:
                    subprocess.run(
                        [sys.executable, "-B", "editor_smoke_test.py"], cwd=root, env=env, check=True
                    )
                if args.workspace:
                    subprocess.run([sys.executable, "-B", "workspace_smoke_test.py"], cwd=root, env=env, check=True)
                report = {
                    "passed": True,
                    "analysis_and_shotlist": json.loads((output / "test-results.json").read_text()),
                }
                if args.editor:
                    report["editor"] = json.loads((output / "editor-test-results.json").read_text())
                if args.workspace:
                    report["workspace"] = json.loads((output / "workspace-test-results.json").read_text())
                if args.report:
                    args.report.parent.mkdir(parents=True, exist_ok=True)
                    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print("Isolated HTTP smoke checks passed; live application data was not used")
            except Exception:
                print(log_path.read_text(encoding="utf-8", errors="replace")[-5000:], file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
