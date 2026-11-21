"""Atomic files and project persistence, with legacy artifact compatibility."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import threading
import uuid
import weakref
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)
_locks = weakref.WeakValueDictionary()
_locks_guard = threading.Lock()
PLAN_ARTIFACTS = frozenset({"plan.json", "resolved.json", "edited-script.txt"})
ANALYSIS_ARTIFACTS = frozenset({"analysis.json", "private-source-map.json", "words.json", "prompt.txt"})


@contextmanager
def path_lock(path):
    key = str(Path(path).resolve())
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _locks[key] = lock
    with lock:
        yield


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False))


class ProjectRepository:
    def __init__(self, folder):
        self.folder = Path(folder)

    @contextmanager
    def locked(self):
        with path_lock(self.folder):
            yield self

    def state(self):
        with self.locked():
            state = read_json(self.folder / "project.json")
            if not isinstance(state, dict):
                raise ValueError("Project state must be an object")
            return state

    def update(self, **changes):
        with self.locked():
            state = self.state()
            state.update(changes)
            write_json(self.folder / "project.json", state)
            return state

    def artifact_path(self, name):
        if name in ANALYSIS_ARTIFACTS:
            storage_id = self.state().get("analysis_storage_id")
            if storage_id:
                if not re.fullmatch(r"[a-f0-9]{64}", storage_id):
                    raise ValueError("Invalid committed analysis revision")
                return self.folder / ".analyses" / storage_id / name
        if name in PLAN_ARTIFACTS:
            state = self.state()
            if state.get("plan_storage_version") == 1:
                revision = state.get("plan_storage_id", state.get("plan_revision", ""))
                if not re.fullmatch(r"[a-f0-9]{64}", revision):
                    raise ValueError("Invalid committed plan revision")
                return self.folder / ".plans" / revision / name
        return self.folder / name

    def read_artifact(self, name):
        with self.locked():
            return read_json(self.artifact_path(name))

    def commit_analysis(self, analysis, mapping, words, prompt, assets, signature, *, segmentation_version=None):
        """Publish a complete analysis together; failed staging preserves the prior revision."""
        with self.locked():
            storage_id = hashlib.sha256((analysis["input_id"] + signature).encode()).hexdigest()
            revision_dir = self.folder / ".analyses" / storage_id
            if not (revision_dir / "complete").is_file():
                for name, value in (("analysis.json", analysis), ("private-source-map.json", mapping), ("words.json", words)):
                    write_json(revision_dir / name, value)
                atomic_write_text(revision_dir / "prompt.txt", prompt)
                atomic_write_text(revision_dir / "complete", storage_id)
            self.update(
                analysis_storage_id=storage_id, analysis_signature=signature,
                **({"analysis_segmentation_version": segmentation_version} if segmentation_version is not None else {}),
                asset_library={**self.state().get("asset_library", {}), **{asset["id"]: asset for asset in assets}},
                analysis_options={key: self.state().get(key) for key in ("language", "describe_visuals")},
                status="analyzed", message="Analysis complete.", progress=100,
                assets=assets, input_id=analysis["input_id"], error=None,
            )
            for name in ANALYSIS_ARTIFACTS:
                try:
                    atomic_write_text(self.folder / name, (revision_dir / name).read_text(encoding="utf-8"))
                except OSError:
                    logger.exception("Could not refresh compatibility artifact %s", self.folder / name)

    def commit_plan(self, plan, resolved, revision):
        """One project.json replacement publishes an entire immutable revision.

        Root artifacts remain compatibility mirrors; application readers always
        follow the committed revision. A failed write cannot expose half a plan.
        """
        with self.locked():
            from pyscenedetect_demo.editor.workspace import preserve_baseline

            baseline = preserve_baseline(self, self.state())
            content_id = hashlib.sha256(
                json.dumps({"plan": plan, "resolved": resolved}, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            revision_dir = self.folder / ".plans" / content_id
            # Never rewrite a published revision, including when the same plan
            # is submitted again. An interrupted, unpublished revision can be rebuilt.
            if not (revision_dir / "complete").is_file():
                write_json(revision_dir / "plan.json", plan)
                write_json(revision_dir / "resolved.json", resolved)
                atomic_write_text(revision_dir / "edited-script.txt", resolved["script"])
                atomic_write_text(revision_dir / "complete", content_id)
            self.update(
                **baseline,
                status="planned",
                message="Edit plan accepted.",
                plan_revision=revision,
                plan_storage_version=1,
                plan_storage_id=content_id,
                output_file=None,
                output_duration_ms=None,
                error=None,
            )
            for name in PLAN_ARTIFACTS:
                try:
                    atomic_write_text(self.folder / name, (revision_dir / name).read_text(encoding="utf-8"))
                except OSError:
                    logger.exception("Could not refresh compatibility artifact %s", self.folder / name)

    def view(self):
        from pyscenedetect_demo.editor.workspace import analysis_current

        with self.locked():
            state = self.state()
            state["has_analysis"] = self.artifact_path("analysis.json").is_file()
            state["has_plan"] = self.artifact_path("resolved.json").is_file()
            state["analysis_current"] = analysis_current(state, state["has_analysis"])
            if state["has_analysis"]:
                state["analysis"] = self.read_artifact("analysis.json")
            if state["has_plan"]:
                state["resolved"] = self.read_artifact("resolved.json")
                state["plan_current"] = state["analysis_current"] and self.read_artifact("plan.json").get("input_id") == state["analysis"].get("input_id")
            else:
                state["plan_current"] = False
            state["ai_response_current"] = state["analysis_current"] and state.get("ai_response_input_id") == state.get("analysis", {}).get("input_id")
            if "ai_response" not in state and state["plan_current"]:
                state["ai_response"] = json.dumps(self.read_artifact("plan.json"), indent=2)
                state["ai_response_current"] = True
            return state


def project_state(folder):
    return ProjectRepository(folder).state()


def update_project(folder, **changes):
    return ProjectRepository(folder).update(**changes)


def list_project_states(root):
    for path in Path(root).glob("*/project.json"):
        try:
            state = ProjectRepository(path.parent).state()
            if not all(isinstance(state.get(key), str) for key in ("id", "status", "created_at")):
                raise ValueError("Project is missing identity or status fields")
            yield path.parent, state
        except (OSError, ValueError, TypeError, KeyError):
            logger.exception("Skipping unreadable project %s; its files are preserved", path)
