# WAIE architecture and change guide

WAIE is the application name. The underlying Scene Scribe repository,
`pyscenedetect_demo` engine package, command names, storage identifiers and
`SCENE_SCRIBE_*` settings retain their existing identities for compatibility.

The application remains one local Python application. HTTP endpoints, command
names, version 1 and version 2 editing responses, original source-media checks,
and processing defaults remain compatible. The refactor separates ownership
without introducing a distributed system or a new runtime framework.

## Responsibilities

| Location | Owns | Must not own |
| --- | --- | --- |
| `web/` | HTTP validation, responses, templates, app composition | Model execution, task scheduling policy, database serialization |
| `services/jobs.py` | Analysis/shot-list use cases, job transitions, enrichment and report operations | FastAPI types or UI rendering |
| `services/editor.py` | Editor uploads, project transitions, scheduling and project access | HTTP exceptions or media algorithms |
| `repositories/jobs.py` | Job snapshots, atomic persistence, backup recovery, deletion boundaries | Background task execution |
| `storage.py` | Atomic files, project locks, immutable plan revisions | HTTP or ML dependencies |
| `execution.py` | Shared resource limit, duplicate-work prevention, task draining, progress subscribers | Feature-specific processing |
| `detection.py` | Scene boundaries, detector construction, representative-frame selection | Report/audio exports |
| `media.py` | FFmpeg frame/audio extraction, probing and hashing | Editorial decisions |
| `transcription.py`, `vision.py`, `captions.py` | Provider-specific adapters and caption normalization | HTTP or project state |
| `pipeline.py`, `shotlist.py` | Existing analysis and shot-list workflows | Web request state |
| `scene_context.py` | Minimal scene context used by editor analysis | Unused report or per-scene audio generation |
| `editor/` | Segmentation, analysis, prompts, validated plans, rendering | HTTP transport |
| `contract/` | Versioned schemas, prompt instructions, pure plan resolution | Media rendering or application persistence |
| `settings.py` | Typed defaults, processing policies and deployment paths | Live mutable project state |

`editing.py` and `web/job_manager.py` remain compatibility facades. New code
should import the focused implementation modules. Provider libraries are
imported lazily so basic analysis does not load speech/vision models.

Button appearance belongs to `web/static/css/buttons.css`, loaded once by the
base template. Use `.btn` for shared typography, sizing, focus, disabled and
interaction states. The filled accent appearance is the default: every editor
action uses `.btn` alone, with no color or size modifiers. `.btn-danger` and
`.btn-sm` are reserved for the separate analysis jobs table. Keep page layout
in `web/static/css/editor.css` and avoid
page-specific button appearance overrides. Templates own markup, while
`web/static/js/editor.js` owns interaction and readiness.

## Configuration

The CLI, app factory and Windows launchers use `AppSettings`. Existing defaults
remain: content detection, threshold 27, minimum scene length 0.8 seconds, tiny
Whisper, local Florence-2, CPU execution, one background operation at a time,
and 30-fps rendering with a maximum picture dimension of 1280 pixels.

Deployment environment variables:

| Variable | Default |
| --- | --- |
| `SCENE_SCRIBE_OUTPUT` | `output`, resolved against the working directory |
| `SCENE_SCRIBE_MODELS` | Installation's `models` directory |
| `SCENE_SCRIBE_SAMPLES` | Installation's `samples` directory |
| `SCENE_SCRIBE_HOST` | `127.0.0.1` |
| `SCENE_SCRIBE_PORT` | `8080` |
| `SCENE_SCRIBE_WORKERS` | `1` shared execution slot |
| `SCENE_SCRIBE_EDITOR` | `1`; `0`, `false` or `no` disables editor integration |

Use `create_app(settings=AppSettings(...))` for injected settings. Explicit CLI
arguments override deployment defaults. Model decoding, segmentation and render
choices are named dataclasses, rather than unrestricted environment switches.
Scene-level transcription retains beam size 1; word-level editor transcription
retains beam size 5. These are intentionally different policies.

The Windows launcher keeps its existing offline/CPU behavior. A normal lifespan
shutdown drains tracked work before saving state. The existing Stop script uses
Windows process termination; interrupted work is marked failed on the next
startup. It is not a resumable job queue.

The launcher checks `/api/health` against the source revision captured when the
server started. It reuses matching servers and restarts outdated, idle servers
through the verified Stop script. It refuses to interrupt active jobs. This
prevents old Python code from being reused with newly changed templates.

## Storage and compatibility

Jobs still use `web_jobs.json`. Writes use temporary files and atomic replacement.
A previous valid database is kept as `web_jobs.json.bak`; damaged bytes are
preserved as `web_jobs.json.corrupt-<id>` before recovery. Corruption is logged.
Repository getters return copies, preventing accidental mutation outside update
operations. Running or queued jobs cannot be deleted.

Projects still use `output/editor/<id>/project.json`. Older projects without
revision metadata continue reading their original root artifacts. New accepted
plans are written to `.plans/<content-id>/` first. One atomic project-state write
publishes the complete revision. Application downloads and rendering follow that
pointer. Root `plan.json`, `resolved.json` and `edited-script.txt` remain compatibility
mirrors; external tools should prefer the HTTP downloads or repository API when
they need a consistent revision. Mirrors are not the transaction boundary.

Editor workspaces require an explicit first **Save draft**, then autosave metadata,
ordered source references, and AI response drafts independently of analysis.
Saved names are immutable. Unsaved work remains in the browser until the user
saves or discards it; switching projects offers Save draft, Discard, or Cancel.
After the first save, source uploads append to the same project immediately.
The editor disables Upload clips until that first save succeeds, including after
New project or deletion resets the workspace.
`services/editor_workspace.py` owns these operations and revision
checks; `editor/workspace.py` defines content identity and analysis freshness.
New workspaces are persisted only after meaningful content is added.

Analyses use the same publication pattern under `.analyses/<content-id>/`.
The previous snapshot remains readable if a new analysis fails. Per-source work
under `.clip-analysis/` is keyed by source hash and analysis settings, so adding or
reordering clips does not repeat unchanged transcription or scene description.
Legacy source units seed this cache on the first update. Analysis changes make
older plans unavailable for generation until a matching response is accepted.
The last successful export remains separately downloadable while new edits are
prepared; each render writes to a new directory before publishing its output.

Sentence segmentation has its own cache version. Reanalysis regroups saved word
timings into sentence units, carries visual context forward, and protects every
new unit overlapping an older required range. Old speech units without word
timings are transcribed again. Projects record `analysis_segmentation_version`
so Analyze clips remains available for an explicit upgrade of existing projects.
The AI handover schema requires a verbatim `script` before the selection; the
resolver checks it against selected words, while accepting saved version 2
selections without this newer field.

No automatic migration rewrites existing analyses or their `input_id`. Copying
an old project's prompt continues exporting the current compact contract.
Malformed projects are logged and skipped individually during listing/recovery;
their files remain available for repair.

JSON storage and locks support one application process. Increasing execution
slots remains within that process. Do not run multiple Uvicorn worker processes
against this output folder. If that becomes necessary, implement transactional
database repositories and a durable work queue behind these service boundaries.

## Contract resources

The authoritative schemas, instructions and examples now live in
`src/pyscenedetect_demo/contract/`, and are included in the wheel. Runtime code
uses package resources and never imports a sibling directory by filename.
`contract/versions.py` owns the shared version-selection rules.

The workspace's sibling `editing-contract/` remains a compatibility entry point.
Its schemas, prompt and examples mirror the package for existing integrations.
Edit the packaged source first, then run:

```powershell
.\.venv\Scripts\python.exe tools\sync_contract.py
.\.venv\Scripts\python.exe tools\sync_contract.py --check
```

Compatibility CLI and test commands in that directory still work. A standalone
clone of Scene Scribe does not require it.

## Making changes safely

1. Identify the owning module above. Keep transport, storage and provider changes
   out of the editorial resolver and segmentation code unless behavior must change.
2. Add a check for the observed behavior at its public boundary. Use temporary
   storage and injected adapters for failure/concurrency cases.
3. Preserve public entry points through wrappers while moving callers gradually.
   Handle intentional behavior corrections separately from output-preserving changes.
4. Run `tools/run_checks.py`, then the relevant optional model smoke checks.
5. For dependency/resource changes, build and check a wheel outside the source
   tree. Keep dependency ranges separate from the known local installed-version
   snapshot in `requirements-installed.txt`.

For example, a new detector belongs in `detection.py` and the available detector
controls; a render-quality option belongs in `RenderProfile`; a new caption
provider belongs behind the image-description adapter. Backend progress events
provide their display label and overall percentage, so adding an internal stage
does not require duplicating pipeline weights in JavaScript.

## Verification

Portable checks, with no running app or downloaded ML models required:

```powershell
.\.venv\Scripts\python.exe tools\run_checks.py
```

This includes the original contract and editor tests, HTTP integration checks,
storage failure/concurrency checks, and generated-media rendering checks. FFmpeg
tests skip when its executables are absent; CI installs FFmpeg on Windows/Linux.

Optional local sample checks, requiring the existing samples and local models:

```powershell
.\.venv\Scripts\python.exe tools\run_local_smoke.py --vision --transcribe --editor
```

That command starts a separate server on a temporary port and uses temporary
output; it does not upload to or modify the user's running application.

Packaging and lint checks after installing `.[web,dev]`:

```powershell
python -m ruff check src tests tools
python -m build --wheel --no-isolation
python tools/check_wheel.py dist/pyscenedetect_demo-0.1.0-py3-none-any.whl
```

CI runs regression, Python lint, JavaScript syntax and standalone-wheel checks on
Windows and Linux. CI configuration is local until these changes are pushed.
