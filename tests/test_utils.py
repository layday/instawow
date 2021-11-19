from __future__ import annotations

import asyncio
from itertools import product
from pathlib import Path
import sys
import time

import pytest

from instawow.manager import find_addon_zip_base_dirs, make_zip_member_filter
from instawow.utils import (
    TocReader,
    bucketise,
    file_uri_to_path,
    merge_intersecting_sets,
    run_in_thread,
    tabulate,
)


@pytest.fixture
def fake_addon():
    yield Path(__file__).parent / 'fixtures' / 'FakeAddon'


def test_find_addon_zip_base_dirs_can_find_explicit_dirs():
    assert set(find_addon_zip_base_dirs(['b/', 'b/b.toc'])) == {'b'}


def test_find_addon_zip_base_dirs_can_find_implicit_dirs():
    assert set(find_addon_zip_base_dirs(['b/b.toc'])) == {'b'}


def test_find_addon_zip_base_dirs_discards_tocless_paths():
    assert set(find_addon_zip_base_dirs(['a', 'b/b.toc', 'c/'])) == {'b'}


def test_find_addon_zip_base_dirs_discards_mismatched_tocs():
    assert not set(find_addon_zip_base_dirs(['a', 'a/b.toc']))


def test_find_addon_zip_base_dirs_accepts_multitoc():
    assert set(find_addon_zip_base_dirs(['a', 'a/a_mainline.toc'])) == {'a'}


@pytest.mark.parametrize('ext', product('Tt', 'Oo', 'Cc'))
def test_find_addon_zip_base_dirs_toc_is_case_insensitive(ext: tuple[str, ...]):
    assert set(find_addon_zip_base_dirs([f'a/a.{"".join(ext)}'])) == {'a'}


def test_make_zip_member_filter_discards_names_with_prefix_not_in_dirs():
    is_member = make_zip_member_filter({'b'})
    assert list(filter(is_member, ['a/', 'b/', 'aa/', 'bb/', 'b/c', 'a/d'])) == ['b/', 'b/c']


def test_loading_toc_from_addon_path(fake_addon: Path):
    TocReader.from_addon_path(fake_addon)
    with pytest.raises(FileNotFoundError):
        TocReader.from_addon_path(fake_addon.parent / 'MissingAddon')


def test_parsing_toc_entries(fake_addon: Path):
    toc_reader = TocReader.from_addon_path(fake_addon)
    assert toc_reader.entries == {
        'Normal': 'Normal entry',
        'Compact': 'Compact entry',
    }


def test_toc_entry_indexing(fake_addon: Path):
    toc_reader = TocReader.from_addon_path(fake_addon)
    assert toc_reader['Normal'] == 'Normal entry'
    assert toc_reader['Compact'] == 'Compact entry'
    assert toc_reader['Indented'] is None
    assert toc_reader['Comment'] is None
    assert toc_reader['Nonexistent'] is None


def test_toc_entry_multiindexing(fake_addon: Path):
    toc_reader = TocReader.from_addon_path(fake_addon)
    assert toc_reader['Normal', 'Compact'] == 'Normal entry'
    assert toc_reader['Compact', 'Normal'] == 'Compact entry'
    assert toc_reader['Indented', 'Normal'] == 'Normal entry'
    assert toc_reader['Nonexistent', 'Indented'] is None
    assert toc_reader['Nonexistent', 'Indented', 'Normal'] == 'Normal entry'


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}


def test_tabulate_spits_out_ascii_table(fake_addon: Path):
    toc_reader = TocReader.from_addon_path(fake_addon)
    data = [('key', 'value'), *toc_reader.entries.items()]
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


@pytest.mark.asyncio
async def test_generator_in_run_in_thread_does_not_lock_up_loop():
    def foo():
        time.sleep(2)
        yield 'foo'

    async def bar():
        await asyncio.sleep(1)
        return ['bar']

    assert [await a for a in asyncio.as_completed([run_in_thread(list)(foo()), bar()])] == [
        ['bar'],
        ['foo'],
    ]
