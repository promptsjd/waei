"""Application composition and lifecycle; business operations live in services."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from pyscenedetect_demo import __version__
from pyscenedetect_demo.execution import BackgroundExecutor
from pyscenedetect_demo.repositories.jobs import JobManager
from pyscenedetect_demo.services.jobs import JobService
from pyscenedetect_demo.settings import AppSettings
from pyscenedetect_demo.runtime import source_revision
from pyscenedetect_demo.web.routes import create_router

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = app.state.settings
    manager = JobManager(data_dir=settings.output_root, output_root=settings.output_root)
    manager.load()
    manager.reset_orphaned_jobs()
    executor = BackgroundExecutor(settings.max_parallel_jobs)
    app.state.executor = executor
    app.state.job_manager = manager
    app.state.job_service = JobService(manager, executor, settings)
    if settings.enable_editor:
        from pyscenedetect_demo.services.editor import EditorService

        app.state.editor_service = EditorService(settings.output_root / "editor", executor, settings)
        app.state.editor_service.recover_interrupted()
    try:
        yield
    finally:
        await executor.close()
        manager.save()


def create_app(*, output_root: str | None = None, settings: AppSettings | None = None) -> FastAPI:
    settings = settings or AppSettings.from_env()
    settings = replace(settings, output_root=Path(output_root or settings.output_root).resolve())
    app = FastAPI(title="WAIE", version=__version__, lifespan=_lifespan)
    app.state.settings = settings
    app.state.source_revision = source_revision()
    app.state.output_root = settings.output_root
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(create_router())
    if settings.enable_editor:
        from pyscenedetect_demo.web.edit_routes import create_edit_router

        app.include_router(create_edit_router())
    return app
