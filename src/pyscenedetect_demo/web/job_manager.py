"""Compatibility import; persistence is independent of the web layer."""

from pyscenedetect_demo.repositories.jobs import JobManager, _utcnow

__all__ = ["JobManager", "_utcnow"]
