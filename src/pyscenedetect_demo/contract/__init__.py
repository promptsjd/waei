"""Versioned editorial contract and packaged schema resources."""

from importlib.resources import files

from .validator import check_schema, read_json, reject_constant, reject_duplicates, resolve

RESOURCES = files(__package__)


def text_resource(name):
    return RESOURCES.joinpath(name).read_text(encoding="utf-8")


__all__ = [
    "RESOURCES",
    "text_resource",
    "check_schema",
    "read_json",
    "reject_constant",
    "reject_duplicates",
    "resolve",
]
