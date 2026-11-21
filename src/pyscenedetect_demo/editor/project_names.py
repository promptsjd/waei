"""Readable project names, independent of their storage IDs."""

import unicodedata


class DuplicateProjectName(ValueError):
    pass


def clean_name(name):
    name = " ".join(name.split())
    if not name or len(name) > 80:
        raise ValueError("Use a project name between 1 and 80 characters.")
    return name


def name_key(name):
    return unicodedata.normalize("NFKC", " ".join(name.split())).casefold()


def available_name(projects, requested=None):
    existing = {name_key(project.get("name") or "") for project in projects}
    if requested is not None:
        name = clean_name(requested)
        if name_key(name) in existing:
            raise DuplicateProjectName("A project with this name already exists. Choose another name.")
        return name
    number = 1
    while name_key(f"Project_{number}") in existing:
        number += 1
    return f"Project_{number}"
