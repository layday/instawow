
import pytest

from instawow.manager import _find_base_dirs, _should_extract
from instawow.utils import bucketise


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


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}
