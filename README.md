# WAIE

Turn recorded talking-head clips into a coherent video using your choice of AI
chat. WAIE analyzes recordings, prepares a prompt, and turns the AI's script
and selection into an edited MP4. No LLM API key or paid AI subscription is required.

**Status:** version 0.1.0, unreleased. Public redistribution still depends on the
inherited engine permission recorded in [LICENSE_STATUS.md](LICENSE_STATUS.md).

## Features

- Named projects, multiple MP4 clips, and autosaved changes after the first save.
- CPU speech transcription and scene descriptions, automatic language detection,
  and the original spoken language preserved.
- The AI reads the full transcript and assembles a coherent, verbatim script
  before choosing footage. The editor preserves recording order.
- Sentences stay together across fillers and pauses. Word counts and elapsed
  time no longer split a sentence; unpunctuated passages stay together.
- The app checks the AI's script against selected recorded words before rendering.
- Preview/download edited videos while preserving original files and the previous
  successful export until its replacement is ready.
- Scene Scribe storyboards, shot lists, thumbnails and command-line exports.

## Try it without a local installation

An optional GitHub Codespaces configuration is included. Once this source is
published to [promptsjd/waei](https://github.com/promptsjd/waei), use:

[Open in GitHub Codespaces](https://codespaces.new/promptsjd/waei)

1. Sign in to GitHub and create a codespace. Each person gets their own instance.
2. Wait for dependency installation and model downloads. First setup can take
   several minutes and requires substantial downloads.
3. Open the **WAIE** entry for port **8080** in the **Ports** panel, then choose
   **Talking-head editor** or append `/editor` to the opened address.
4. Follow the editing steps below. Download your finished MP4 before deleting
   the codespace, and stop the codespace when finished.

This mode uploads videos to your GitHub-hosted codespace. GitHub account quotas
and possible charges apply. Keep the forwarded port **private**. The configuration
has not yet been tested in a live Codespace. See [hosting options](docs/HOSTING.md).

**GitHub Pages cannot run this app.** It serves static files, without the Python
backend, FFmpeg or model execution. A public editor without GitHub sign-in needs
a separate backend and per-user project isolation. No public demo is deployed.

## Install on your computer

Use Python **3.11-3.13** and install **FFmpeg/ffprobe** on `PATH` with `libx264`
and AAC support. CI targets Python 3.11 on Windows/Linux. No GPU is required.
Internet is needed for installation and the first model downloads.

Clone or download the source and open a terminal in the repository root:

```text
python -m venv .venv
```

Activate it with `.\.venv\Scripts\Activate.ps1` in Windows PowerShell or
`source .venv/bin/activate` on macOS/Linux. If PowerShell blocks activation,
use `.\.venv\Scripts\python.exe` in place of `python` below.

```text
python -m pip install --upgrade pip
python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
python -m pip install -e ".[web,vision]"
python download_models.py
scene-web --host 127.0.0.1 --port 8080
```

The PyTorch command is for Windows/Linux CPU installations. On macOS, install
`torch torchvision` from the normal package index instead. Models download to
`models/`: Florence-2-base and faster-whisper-tiny, with revision records.
The editor uses both. For the separate storyboard tools without visual
descriptions, installing `.[web]` is sufficient.

Open **http://127.0.0.1:8080/editor**. On Windows, **Start WAIE.cmd** and
**Stop WAIE.cmd** start/stop the local server after installation. The Windows
launcher uses offline model access, so download models first. Stop a manually
launched server with Ctrl+C.

## Edit a video

1. Enter a name or keep the suggestion, then select **Save draft**.
   **Upload clips** stays disabled until this first save succeeds.
2. Upload MP4 clips. Optionally add **Topic** and **Context** to explain the
   subject. Later changes autosave; wait for **Saved** before leaving.
3. Select **Analyze clips**, then **Copy prompt** when it finishes.
4. Paste the complete prompt into your AI chat and request the complete JSON
   response. It includes the intended spoken script and matching unit IDs.
5. Paste it into **Paste AI response** and select **Generate Video**. Validation
   checks it before automatically rendering the selected footage.
6. Read the retained script, play the result, and use **Download Video**.

Select saved work from the project list. **New project** creates an unsaved
workspace. **Delete project** confirms before removing its uploaded copies,
analysis and exports; original files elsewhere stay intact.
Existing projects can upgrade sentence boundaries through **Analyze clips**;
copy the refreshed prompt and obtain a new AI response afterward. Older responses
without `script` remain supported for compatibility.

## Data and limitations

In a local installation, processing runs on your computer. WAIE makes no external
LLM calls. Pasting a prompt into an AI service shares its transcript and scene
descriptions with that service. Project data lives in `output/`; downloaded
models live in `models/`. Both are excluded from source exports.

Tiny Whisper can mishear words and timestamps. Sentence punctuation is estimated
and cannot guarantee seamless joins. Descriptions use sampled still frames and
can misdescribe actions. Review the script and video. Rendering uses CPU at
30 fps and may adjust each selected range by up to one frame.

There is no user authentication or per-user project ownership. Use a trusted local
computer or your own private codespace. A shared public instance would expose
the same project library to every visitor.

## Other tools and development

The storyboard interface is at `/`; API documentation is at `/docs`.

| Command | Purpose |
| --- | --- |
| `scene-web` | Start WAIE |
| `scene-analyzer input.mp4 --output output` | Export a storyboard |
| `scene-shotlist input.mp4` | Export shot boundaries and thumbnails |
| `scene-report output/video/scenes.json` | Rebuild an HTML report |
| `scene-visuals output/video/scenes.json` | Describe existing scene images |

Use `--help` for options. Print HTML reports to PDF, or optionally install
WeasyPrint and its native dependencies for automatic shot-list PDF export.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup/checks,
[ARCHITECTURE.md](ARCHITECTURE.md) for module ownership,
[CHANGELOG.md](CHANGELOG.md) for changes, and
[docs/RELEASING.md](docs/RELEASING.md) for a clean source upload.

## Credits and feedback

WAIE builds on [seki2020/scene-scribe](https://github.com/seki2020/scene-scribe),
base commit `e84d871387979918793537579412683039a1b11d`. The engine package
`pyscenedetect_demo`, `scene-*` commands and `SCENE_SCRIBE_*` settings retain their
names for compatibility. App and AI contract versions are separate.

The intended WAIE license is MIT, pending engine permission. No license for the
combined codebase is granted by this README. See [license status](LICENSE_STATUS.md)
and [third-party notices](THIRD_PARTY_NOTICES.md).

**Send feedback** opens a dialog with the address, **Copy email address** and
**Open email app**. You can also email
[promptsmithjd@gmail.com](mailto:promptsmithjd@gmail.com). **Repo** opens
[promptsjd/waei](https://github.com/promptsjd/waei).
