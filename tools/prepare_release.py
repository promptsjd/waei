"""Export reviewable source without local data or Git history. Never overwrites."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = (
    ".editorconfig", ".gitattributes", ".gitignore", "README.md", "ARCHITECTURE.md", "CHANGELOG.md",
    "CONTRIBUTING.md", "LICENSE_STATUS.md", "THIRD_PARTY_NOTICES.md", "pyproject.toml",
    "download_models.py", "test_editor_units.py", "smoke_test.py", "editor_smoke_test.py",
    "workspace_smoke_test.py", "Start WAIE.cmd", "Stop WAIE.cmd", "Start-LocalServer.ps1",
    "Stop-LocalServer.ps1", "Run Sample Tests.cmd", "Run Editor Tests.cmd",
)
TREES = ("src", "tests", "tools", "docs", ".github", ".devcontainer")
SUFFIXES = {".py", ".md", ".json", ".html", ".css", ".js", ".cjs", ".toml", ".yml", ".yaml", ".txt"}
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".git", ".venv"}


def source_files(root):
    paths = [root / name for name in ROOT_FILES]
    # Once permission is recorded, include the actual license too.
    paths.extend(path for name in ("LICENSE", "COPYING", "NOTICE") if (path := root / name).is_file())
    for tree in TREES:
        for path in sorted((root / tree).rglob("*")):
            relative = path.relative_to(root)
            if SKIP_PARTS.intersection(relative.parts) or any(part.endswith(".egg-info") for part in relative.parts):
                continue
            if path.is_symlink():
                raise ValueError(f"Refusing source symlink: {relative}")
            if path.is_file() and (path.suffix in SUFFIXES or path.name == "Dockerfile"):
                paths.append(path)
    for path in paths:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Missing or unsafe source file: {path.relative_to(root)}")
    return sorted(set(paths))


def export(root, destination):
    root, destination = root.resolve(), destination.resolve()
    archive = destination.with_name(destination.name + ".zip")
    if destination.exists() or archive.exists():
        raise FileExistsError("Export directory or ZIP already exists. Choose a new --destination.")
    if root.is_relative_to(destination) or any(destination.is_relative_to(root / tree) for tree in TREES):
        raise ValueError("Export must be outside source trees, for example release/waie-source.")
    paths = source_files(root)
    manifest = {"files": {}}
    destination.mkdir(parents=True)
    for path in paths:
        relative = path.relative_to(root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        manifest["files"][relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    (destination / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                output.write(path, Path(destination.name) / path.relative_to(destination))
    return archive, len(paths)


def main():
    version = next(line.split('"')[1] for line in (ROOT / "src/pyscenedetect_demo/__init__.py").read_text().splitlines()
                   if line.startswith("__version__ ="))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "release" / f"waie-{version}-source")
    args = parser.parse_args()
    try:
        archive, count = export(ROOT, args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Prepared {count} source files: {archive}")
    print("Publication still depends on the engine permission recorded in LICENSE_STATUS.md.")


if __name__ == "__main__":
    main()
