"""Install and start a personal WAIE Codespaces instance, without public ports."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def python_path(root):
    return root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def setup(root=ROOT):
    python = python_path(root)
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
    commands = [
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        [str(python), "-m", "pip", "install", "torch", "torchvision", "--index-url",
         "https://download.pytorch.org/whl/cpu"],
        [str(python), "-m", "pip", "install", "-e", ".[web,vision]"],
        [str(python), "download_models.py"],
    ]
    for command in commands:
        subprocess.run(command, cwd=root, check=True)


def health(url):
    try:
        with urlopen(url + "/api/health", timeout=1) as response:
            return json.load(response)
    except (OSError, ValueError):
        return None


def start(root=ROOT, port=8080):
    python = python_path(root)
    if not python.is_file():
        raise RuntimeError("Run python tools/codespace.py setup first.")
    output = root / "output"
    url = f"http://127.0.0.1:{port}"
    existing = health(url)
    if existing:
        revision = subprocess.check_output(
            [str(python), "-c", "from pyscenedetect_demo.runtime import source_revision; print(source_revision())"],
            cwd=root, text=True,
        ).strip()
        if (existing.get("application") == "scene-scribe"
                and existing.get("output_root") == str(output.resolve())
                and existing.get("revision") == revision):
            print(f"WAIE is already running at {url}/editor")
            return
        raise RuntimeError("Port is in use by another or outdated server. Stop/restart the codespace.")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", port))
    output.mkdir(exist_ok=True)
    env = dict(os.environ, SCENE_SCRIBE_OUTPUT=str(output), SCENE_SCRIBE_HOST="127.0.0.1",
               SCENE_SCRIBE_PORT=str(port), SCENE_SCRIBE_MODELS=str(root / "models"),
               HF_HOME=str(root / "models/.hf-cache"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               CUDA_VISIBLE_DEVICES="-1", PYTHONDONTWRITEBYTECODE="1")
    with (output / "codespace-server.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(python), "-m", "pyscenedetect_demo.web.main"], cwd=root, env=env,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("WAIE stopped during startup. Check output/codespace-server.log.")
        result = health(url)
        if result and result.get("application") == "scene-scribe" and result.get("output_root") == str(output.resolve()):
            print(f"WAIE ready at {url}/editor. Open port {port} in the Codespaces Ports panel; keep it Private.")
            return
        time.sleep(.2)
    process.terminate()
    process.wait(timeout=10)
    raise TimeoutError("WAIE did not become ready. Check output/codespace-server.log.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "start"))
    args = parser.parse_args()
    try:
        (setup if args.action == "setup" else start)()
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
