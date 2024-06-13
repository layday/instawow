from __future__ import annotations

import asyncio
import importlib.resources
import sys
import time
from pathlib import Path

import pytest

from instawow._utils.aio import run_in_thread
from instawow._utils.iteration import bucketise, merge_intersecting_sets
from instawow._utils.text import tabulate
from instawow._utils.web import file_uri_to_path
from instawow.matchers.addon_toc import TocReader


@pytest.fixture
def fake_addon_toc():
    with importlib.resources.as_file(
        importlib.resources.files(__spec__.parent) / 'fixtures' / 'FakeAddon' / 'FakeAddon.toc'
    ) as file:
        yield file


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}


def test_tabulate_spits_out_ascii_table(fake_addon_toc: Path):
    toc_reader = TocReader.from_path(fake_addon_toc)
    data = [('key', 'value'), *toc_reader.items()]
    assert tabulate(data) == (
        '  key        value    \n'
        '-------  -------------\n'
        'Normal   Normal entry \n'
        'Compact  Compact entry'
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
                run_in_thread(list)(
                    foo(),  # pyright: ignore[reportArgumentType]
                ),
                bar(),
            ]
        )
    ] == [
        ['bar'],
        ['foo'],
    ]
