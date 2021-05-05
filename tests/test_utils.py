import asyncio
from pathlib import Path
import sys
import time

import pytest

from instawow.manager import find_zip_base_dirs, make_zip_member_filter
from instawow.utils import (
    TocReader,
    bucketise,
    file_uri_to_path,
    is_outdated,
    merge_intersecting_sets,
    run_in_thread,
    tabulate,
)


@pytest.fixture
def fake_addon():
    yield Path(__file__).parent / 'fixtures' / 'FakeAddon'


def test_find_zip_base_dirs_can_find_explicit_dirs():
    assert find_zip_base_dirs(['b/', 'b/b.toc']) == {'b'}


def test_find_zip_base_dirs_can_find_implicit_dirs():
    assert find_zip_base_dirs(['b/b.toc']) == {'b'}


def test_find_zip_base_dirs_discards_files_in_root():
    assert find_zip_base_dirs(['a', 'b/b.toc', 'c/']) == {'b', 'c'}


def test_make_zip_member_filter_discards_names_with_prefix_not_in_dirs():
    is_member = make_zip_member_filter({'b'})
    assert list(map(is_member, ['a/', 'b/', 'aa/', 'bb/'])) == [False, True, False, False]


def test_loading_toc_from_addon_path(fake_addon):
    TocReader.from_addon_path(fake_addon)
    with pytest.raises(FileNotFoundError):
        TocReader.from_addon_path(fake_addon.parent / 'MissingAddon')


def test_parsing_toc_entries(fake_addon):
    toc_reader = TocReader.from_addon_path(fake_addon)
    assert toc_reader.entries == {
        'Normal': 'Normal entry',
        'Compact': 'Compact entry',
    }


def test_toc_entry_indexing(fake_addon):
    toc_reader = TocReader.from_addon_path(fake_addon)
    assert toc_reader['Normal'] == 'Normal entry'
    assert toc_reader['Compact'] == 'Compact entry'
    assert toc_reader['Indented'] is None
    assert toc_reader['Comment'] is None
    assert toc_reader['Nonexistent'] is None


def test_toc_entry_multiindexing(fake_addon):
    toc_reader = TocReader.from_addon_path(fake_addon)
    assert toc_reader['Normal', 'Compact'] == 'Normal entry'
    assert toc_reader['Compact', 'Normal'] == 'Compact entry'
    assert toc_reader['Indented', 'Normal'] == 'Normal entry'
    assert toc_reader['Nonexistent', 'Indented'] is None
    assert toc_reader['Nonexistent', 'Indented', 'Normal'] == 'Normal entry'


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}


def test_tabulate_spits_out_ascii_table(fake_addon):
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


@pytest.mark.iw_no_mock
@pytest.mark.asyncio
async def test_is_outdated_works_in_variety_of_scenarios(monkeypatch, aresponses, iw_temp_dir):
    pypi_version = iw_temp_dir.joinpath('.pypi_version')
    if pypi_version.exists():
        pypi_version.unlink()

    # 'dev' in version number, version not cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0-dev')
        assert await is_outdated() == (False, '')

    # Update check disabled, version not cached
    with monkeypatch.context() as patcher:
        patcher.setenv('INSTAWOW_AUTO_UPDATE_CHECK', '0')
        assert await is_outdated() == (False, '')

    # Endpoint not responsive, version not cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            aresponses.Response(status=500),
        )
        assert await is_outdated() == (False, '0.0.0')

    # Endpoint responsive, version not cached and version different
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            {'info': {'version': '1.0.0'}},
        )
        assert await is_outdated() == (True, '1.0.0')

    # 'dev' in version number, version cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0-dev')
        assert await is_outdated() == (False, '')

    # Update check disabled, version cached
    with monkeypatch.context() as patcher:
        patcher.setenv('INSTAWOW_AUTO_UPDATE_CHECK', '0')
        assert await is_outdated() == (False, '')

    # Endpoint not responsive, version cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            aresponses.Response(status=500),
        )
        assert await is_outdated() == (True, '1.0.0')

    # Endpoint responsive, version cached and version same
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            {'info': {'version': '1.0.0'}},
        )
        assert await is_outdated() == (True, '1.0.0')

    # Endpoint responsive, version cached and version different
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '1.0.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            {'info': {'version': '1.0.0'}},
        )
        assert await is_outdated() == (False, '1.0.0')


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
