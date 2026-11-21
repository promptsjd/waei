"""Validate first, then atomically publish an immutable plan revision."""

import hashlib
import html
import json
import re
from pyscenedetect_demo import contract
from pyscenedetect_demo.storage import ProjectRepository


_SPACE_ENTITY = re.compile(r"&#(?:[xX][0-9a-fA-F]+|[0-9]+);|&nbsp;")


def _clipboard_formatting(text):
    """Remove copied Markdown line breaks and HTML spaces outside JSON strings."""
    output = []
    quoted = escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "\\" and index + 1 < len(text) and text[index + 1] in "\r\n":
            index += 1
            continue
        elif char == "&":
            entity = _SPACE_ENTITY.match(text, index)
            if entity and html.unescape(entity.group()).isspace():
                output.append(" ")
                index = entity.end()
                continue
        output.append(char)
        index += 1
    return "".join(output)


def _unfence(text):
    text = text.strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```json", "```"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text


def parse_plan_text(text):
    def load(value):
        return json.loads(value, object_pairs_hook=contract.reject_duplicates, parse_constant=contract.reject_constant)

    try:
        return load(_unfence(text))
    except json.JSONDecodeError:
        normalized = _unfence(_clipboard_formatting(text))
        if normalized == _unfence(text):
            raise
        return load(normalized)


def accept_plan(folder, text):
    plan = parse_plan_text(text)
    analysis = ProjectRepository(folder).read_artifact("analysis.json")
    mapping = ProjectRepository(folder).read_artifact("private-source-map.json")
    resolved = contract.resolve(analysis, plan, mapping)
    revision = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    ProjectRepository(folder).commit_plan(plan, resolved, revision)
    return resolved
