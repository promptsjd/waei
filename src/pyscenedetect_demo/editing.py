"""Compatibility API for existing editor integrations and saved projects."""

from pyscenedetect_demo import contract
from pyscenedetect_demo.settings import INSTALL_ROOT as REPO
from pyscenedetect_demo.storage import read_json, write_json, project_state, update_project
from pyscenedetect_demo.media import run_command, probe, file_hash
from pyscenedetect_demo.editor.segmentation import build_units
from pyscenedetect_demo.editor.prompting import prompt_analysis, write_prompt
from pyscenedetect_demo.editor.analysis import analyze_project
from pyscenedetect_demo.editor.plans import accept_plan
from pyscenedetect_demo.editor.rendering import render_project

CONTRACT = contract.RESOURCES


def contract_module():
    return contract


__all__ = [
    "REPO",
    "CONTRACT",
    "read_json",
    "write_json",
    "project_state",
    "update_project",
    "run_command",
    "probe",
    "file_hash",
    "build_units",
    "prompt_analysis",
    "write_prompt",
    "analyze_project",
    "accept_plan",
    "render_project",
    "contract_module",
]
