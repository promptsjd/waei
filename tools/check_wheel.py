"""Check packaged resources and import a wheel independently of the source tree."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


SMOKE = r"""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0, sys.argv[1])
import pyscenedetect_demo
from pyscenedetect_demo import contract, editing
from pyscenedetect_demo.web import create_app, STATIC_DIR
from jinja2 import Environment, FileSystemLoader
assert Path(pyscenedetect_demo.__file__).is_relative_to(Path(sys.argv[1]))
assert (STATIC_DIR / 'js/job-detail.js').is_file()
templates = Environment(loader=FileSystemLoader(STATIC_DIR.parent / 'templates'))
for name in ('base.html', 'index.html', 'editor.html', 'job_detail.html'):
    templates.get_template(name)
for version in ('', 'v1/'):
    examples = contract.RESOURCES / ('examples/' + version)
    result = contract.resolve(contract.read_json(examples / 'llm-input.json'),
        contract.read_json(examples / 'llm-edit-plan.json'),
        contract.read_json(examples / 'private-source-map.json'))
    assert result['duration_ms'] == 15000
with tempfile.TemporaryDirectory() as directory:
    folder = Path(directory)
    editing.write_json(folder / 'project.json', {'status': 'analyzed'})
    editing.write_json(folder / 'analysis.json', contract.read_json(contract.RESOURCES / 'examples/llm-input.json'))
    assert 'REQUIRED RESPONSE JSON SCHEMA' in editing.write_prompt(folder)
create_app()
print('Standalone wheel: imports, templates, static assets, both contracts and prompt generation passed')
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="scene-wheel-check-") as directory:
        with zipfile.ZipFile(args.wheel) as archive:
            archive.extractall(directory)
        return subprocess.run([sys.executable, "-I", "-B", "-c", SMOKE, directory], cwd=directory).returncode


if __name__ == "__main__":
    raise SystemExit(main())
