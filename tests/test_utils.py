
from pathlib import Path

import pytest

from instawow.manager import _find_base_dirs, _should_extract
from instawow.utils import TocReader, bucketise


@pytest.fixture
def fake_addon():
    yield Path(__file__).parent / 'fixtures' / 'FakeAddon'


def test_find_base_dirs_can_find_explicit_dirs():
    assert _find_base_dirs(['b/', 'b/b.toc']) == {'b'}


def test_find_base_dirs_can_find_implicit_dirs():
    assert _find_base_dirs(['b/b.toc']) == {'b'}


def test_find_base_dirs_discards_resource_forks():
    assert _find_base_dirs(['b/', '__MACOSX/']) == {'b'}


def test_find_base_dirs_discards_files_in_root():
    assert _find_base_dirs(['a', 'b/b.toc', 'c/']) == {'b', 'c'}


def test_should_extract_discards_names_with_prefix_not_in_dirs():
    is_member = _should_extract({'b'})
    assert list(map(is_member, ['a/', 'b/', 'aaa/'])) == [False, True, False]


def test_loading_toc_from_path(fake_addon):
    TocReader.from_path(fake_addon / 'FakeAddon.toc')
    with pytest.raises(FileNotFoundError):
        TocReader.from_path(fake_addon / 'MissingToc.toc')


def test_loading_toc_from_path_name(fake_addon):
    TocReader.from_path_name(fake_addon)
    with pytest.raises(FileNotFoundError):
        TocReader.from_path_name(fake_addon.parent / 'MissingAddon')


def test_parsing_toc_entries(fake_addon):
    toc_reader = TocReader.from_path_name(fake_addon)
    assert toc_reader.entries == {'Normal': 'Normal entry',
                                  'Compact': 'Compact entry',}


def test_indexing_toc_entries(fake_addon):
    toc_reader = TocReader.from_path_name(fake_addon)
    assert toc_reader['Normal'] == ('Normal', 'Normal entry')
    assert toc_reader['Compact'] == ('Compact', 'Compact entry')
    assert toc_reader['Indented'] == ('Indented', '')
    assert toc_reader['Comment'] == ('Comment', '')
    assert toc_reader['Nonexistent'] == ('Nonexistent', '')


def test_multiindexing_toc_entries(fake_addon):
    toc_reader = TocReader.from_path_name(fake_addon)
    assert toc_reader['Normal', 'Compact'] == ('Normal', 'Normal entry')
    assert toc_reader['Compact', 'Normal'] == ('Compact', 'Compact entry')
    assert toc_reader['Indented', 'Normal'] == ('Normal', 'Normal entry')
    assert toc_reader['Nonexistent', 'Indented', 'Normal'] == ('Normal', 'Normal entry')


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}
