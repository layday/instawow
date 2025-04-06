from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

from instawow._utils.aio import run_in_thread
from instawow._utils.dist_metadata import (
    _iter_dist_infos,
    _parse_entry_points_txt,
    iter_entry_point_plugins,
)
from instawow._utils.iteration import bucketise, merge_intersecting_sets
from instawow._utils.text import tabulate
from instawow._utils.web import file_uri_to_path
from instawow._version import get_version


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}


def test_tabulate_spits_out_ascii_table():
    data = [('key', 'value'), ('abc def', 'hhhdhhdhfhh'), ('dskfjsdfksdkf', 'huh')]
    assert (
        tabulate(data)
        == """\
key            value      \

-------------  -----------
abc def        hhhdhhdhfhh
dskfjsdfksdkf  huh        \
"""
    )


def test_merge_intersecting_sets_in_noncontiguous_collection():
    collection = [
        {'a'},
        {'b', 'c'},
        {'a', 'd'},
        {'e'},
        {'c', 'f'},
        {'g', 'a'},
    ]
    output = [
        {'a', 'd', 'g'},
        {'b', 'c', 'f'},
        {'e'},
    ]
    assert sorted(merge_intersecting_sets(collection)) == output


@pytest.mark.skipif(sys.platform == 'win32', reason='platform dependent')
def test_file_uri_to_path_posix_leading_slash_is_preserved():
    uri = Path('/foo/bar').as_uri()
    assert uri == 'file:///foo/bar'
    assert file_uri_to_path(uri) == '/foo/bar'


@pytest.mark.skipif(sys.platform != 'win32', reason='platform dependent')
def test_file_uri_to_path_win32_leading_slash_is_stripped():
    uri = Path('C:/foo/bar').as_uri()
    assert uri == 'file:///C:/foo/bar'
    assert file_uri_to_path(uri) == 'C:/foo/bar'


async def test_generator_in_run_in_thread_does_not_lock_up_loop():
    def foo():
        time.sleep(2)
        yield 'foo'

    async def bar():
        await asyncio.sleep(1)
        return ['bar']

    assert [
        await a
        for a in asyncio.as_completed(
            [
                run_in_thread(list)(foo()),
                bar(),
            ]
        )
    ] == [
        ['bar'],
        ['foo'],
    ]


def test_reading_entry_point_plugins_from_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dist_info = tmp_path / f'instawow-{get_version()}.dist-info'
    dist_info.mkdir()
    with _iter_dist_infos([os.fspath(tmp_path)]) as dist_infos:
        assert [os.fspath(d) for d in dist_infos] == [os.fspath(dist_info)]

    entry_points_txt = """\
[console_scripts]
foo = foomod:main
# One which depends on extras:
foobar = foomod:main_bar [bar,baz]

# pytest plugins refer to a module, so there is no ':obj'
[pytest11]
nbval = nbval.plugin
"""
    assert list(_parse_entry_points_txt(entry_points_txt)) == [
        ('console_scripts', 'foo', 'foomod:main'),
        ('console_scripts', 'foobar', 'foomod:main_bar'),
        ('pytest11', 'nbval', 'nbval.plugin'),
    ]

    monkeypatch.setattr('sys.path', [tmp_path])
    (dist_info / 'entry_points.txt').write_text(entry_points_txt, encoding='utf-8')
    assert [n for n, _ in iter_entry_point_plugins('console_scripts')] == ['foo', 'foobar']
    assert [n for n, _ in iter_entry_point_plugins('pytest11')] == ['nbval']
