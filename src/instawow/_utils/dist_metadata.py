"""
Utilities for reading distribution metadata from $PYTHONPATH
on the filesystem.

This lacks support for zip and other exotic paths, and `egg-info`s, which
are non-standard.

Spec: https://packaging.python.org/en/latest/specifications/entry-points/
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import ExitStack, contextmanager
from functools import partial, reduce
from pathlib import Path


class DistNotFoundError(Exception):
    pass


@contextmanager
def _iter_dist_infos(paths: list[str]):
    with ExitStack() as exit_stack:
        yield (
            p
            for e in map(Path, paths)
            if e.is_dir()
            for p in exit_stack.enter_context(os.scandir(e or '.'))
            if p.name.endswith('.dist-info')
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
    with _iter_dist_infos(sys.path) as dist_infos:
        for dist_info in dist_infos:
            entry_points_path = Path(dist_info.path, 'entry_points.txt')
            if entry_points_path.is_file():
                for group, name, object_ref in _parse_entry_points_txt(
                    entry_points_path.read_text(encoding='utf-8')
                ):
                    if group == wanted_group:
                        yield name, partial(_import_plugin, object_ref)


def get_version(wanted_dist_name: str):
    import email

    with _iter_dist_infos(sys.path) as dist_infos:
        for dist_info in dist_infos:
            dist_name, *_ = dist_info.name.partition('-')
            if dist_name == wanted_dist_name:
                break
        else:
            raise DistNotFoundError

    metadata = email.message_from_bytes(
        Path(dist_info.path, 'METADATA').read_bytes(),
    )
    return metadata['Version']
