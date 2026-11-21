# Contributing to WAIE

Public release is pending the engine permission in
[LICENSE_STATUS.md](LICENSE_STATUS.md). These instructions describe the planned
contribution workflow once rights are cleared; no open-source grant is implied.

## Development setup

Use Python 3.11–3.13, FFmpeg/ffprobe, Git, and Node.js 22 or later. Create a
virtual environment as in [README.md](README.md), activate it, and install:

```text
python -m pip install -e ".[web,dev]"
```

Vision dependencies and model downloads are optional for the core regression
suite. Keep personal clips, downloaded models, and project output out of Git.

## Checks before a pull request

From the repository root with the environment active:

```text
python tools/run_checks.py
node --test tests/editor-ui.test.cjs
python -m ruff check src tests tools
node --check src/pyscenedetect_demo/web/static/js/app.js
node --check src/pyscenedetect_demo/web/static/js/editor.js
node --check src/pyscenedetect_demo/web/static/js/job-detail.js
python -m build --wheel --no-isolation
```

Then use `python tools/check_wheel.py PATH_TO_WHEEL` on the generated wheel.
Together these commands cover contracts, saved projects, HTTP behavior,
Node-based editor interactions and generated-media FFmpeg operations using temporary output.
They do not need existing saved projects. GitHub Actions runs on Windows/Linux.

Review UI changes at desktop/narrow widths, including keyboard focus and
scrolling. Keep the feedback bar clear of the last page control.

`tools/run_local_smoke.py` is optional and requires the original developer's
local-model sample fixtures, which are excluded from this source release.
It is not a prerequisite for a clean contributor checkout.

## Working on a change

1. Start a focused branch, for example `git switch -c fix/upload-error`.
2. Keep changes in the relevant module and preserve existing user work.
3. Add meaningful regression coverage for behavior changes. Simple cosmetic
   or documentation changes do not need tests that merely repeat their text.
4. Run checks and describe their results in the pull request.
5. Add an entry under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).

See [ARCHITECTURE.md](ARCHITECTURE.md) for ownership and compatibility.
`pyscenedetect_demo`, `scene-*` commands, `SCENE_SCRIBE_*` settings, storage IDs,
and existing editing schemas require migration planning before incompatible
changes. App release versions and AI schema versions are independent.

## Issues and pull requests

Include Python/OS information, steps, expected/actual behavior, and sanitized
logs. Redact personal paths, transcripts, recordings, and credentials. Use
generated or explicitly shareable media in reproducible examples.

Preserve attribution; do not add code/assets whose redistribution rights are
unclear. Document dependencies in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
For a potential security issue, contact `promptsmithjd@gmail.com` privately
before filing a public issue. The app is for a trusted local computer and has
no authentication; it should not be exposed as a public hosted service.

Maintainers follow [docs/RELEASING.md](docs/RELEASING.md). Feature/fix pull
requests should not bump the version unless preparing a release.
