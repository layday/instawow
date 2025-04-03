"""
Utilities for reading entry-point plugins from $PYTHONPATH
on the filesystem.

This lacks support for zip and other exotic paths and `egg-info`s, which
are non-standard.

Spec: https://packaging.python.org/en/latest/specifications/entry-points/
"""

from __future__ import annotations

import importlib
import os
import sys
from functools import partial, reduce
from pathlib import Path


def _get_dist_infos(path: list[str]):
    return (
        p for e in path if Path(e).is_dir() for p in os.scandir(e) if p.name.endswith('.dist-info')
    )


def _parse_entry_points_txt(content: str):
    group = None
    for line in filter(None, map(str.strip, content.splitlines())):
        if line.startswith('#'):
            continue
        elif line.startswith('[') and line.endswith(']'):
            group = line.strip('[]')
        else:
            extras_pos: int = line.find('[')
            if extras_pos > -1:
                line = line[:extras_pos]
            name, _, object_ref = map(str.strip, line.partition('='))
            if object_ref:
                yield group, name, object_ref


def _import_plugin(object_ref: str):
    module, _, qualified_name = map(str.strip, object_ref.partition(':'))
    plugin = importlib.import_module(module)
    if qualified_name:
        plugin = reduce(getattr, qualified_name.split('.'), plugin)
    return plugin


def iter_entry_point_plugins(wanted_group: str):
    for subpath in _get_dist_infos(sys.path):
        entry_points_path = Path(subpath.path, 'entry_points.txt')
        if entry_points_path.is_file():
            for group, name, object_ref in _parse_entry_points_txt(
                entry_points_path.read_text(encoding='utf-8')
            ):
                if group == wanted_group:
                    yield name, partial(_import_plugin, object_ref)
