# Prepare a GitHub source release

The app version lives in `src/pyscenedetect_demo/__init__.py`. Version 0.1.0 is
an unreleased candidate. AI contract versions are separate.

## Prepare and verify

Install contributor dependencies and run from the repository root:

```text
python -m pip install -e ".[web,dev]"
python tools/run_checks.py
node --test tests/editor-ui.test.cjs
python -m ruff check src tests tools
python -m build --wheel --no-isolation
python tools/check_wheel.py dist/pyscenedetect_demo-0.1.0-py3-none-any.whl
python tools/prepare_release.py
```

The last command creates `release/waie-0.1.0-source/` and its ZIP. It copies an
explicit set of source/docs/configuration files. It excludes Git history,
recordings, model weights, saved projects, environment files, virtual
environments, caches, machine notes and old build artifacts. Existing exports
are never overwritten; remove an old export yourself or choose `--destination`.

Verify the exported copy too: create its own environment or use your existing
interpreter with its `src/` on `PYTHONPATH`, run `tools/run_checks.py`, and inspect
its README, source manifest and ZIP. The source manifest records each exported
file's SHA-256 hash. This is a source package, not an executable installer.

## Publication status

Resolve the inherited engine permission in [LICENSE_STATUS.md](../LICENSE_STATUS.md)
before a public source release. Record the actual permission and add the
authorized license text/metadata; do not assign MIT merely because it is intended.
Third-party dependencies/models have separate terms listed in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

Once ready to publish, use the **exported directory**, keeping the working
checkout and its original engine history intact. Create an empty GitHub repository
or inspect the existing repository before integrating with it. For a new, empty
repository only:

```text
git init -b main
git add .
git diff --cached --stat
git commit -m "Prepare WAIE 0.1.0 source"
git remote add origin https://github.com/promptsjd/waei.git
git push -u origin main
```

Inspect the staged files before committing. Do not force-push over an existing
repository. Check Windows/Linux Actions results before tagging an actual release.
This preparation workflow does not push, publish, tag or alter any Git remote.

## Browser access

The `.devcontainer/` configuration prepares a personal Codespaces instance;
the container build still needs a live validation after upload. GitHub Pages
cannot run the Python editor. See [HOSTING.md](HOSTING.md) for the supported
trial flow and the work needed for a public service.
