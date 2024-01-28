from __future__ import annotations

from itertools import product

import pytest

from instawow.archives import find_archive_addon_tocs, make_archive_member_filter_fn


def test_find_archive_addon_tocs_can_find_explicit_dirs():
    assert {h for _, h in find_archive_addon_tocs(['b/', 'b/b.toc'])} == {'b'}


def test_find_archive_addon_tocs_can_find_implicit_dirs():
    assert {h for _, h in find_archive_addon_tocs(['b/b.toc'])} == {'b'}


def test_find_archive_addon_tocs_discards_tocless_paths():
    assert {h for _, h in find_archive_addon_tocs(['a', 'b/b.toc', 'c/'])} == {'b'}


def test_find_archive_addon_tocs_discards_mismatched_tocs():
    assert not {h for _, h in find_archive_addon_tocs(['a', 'a/b.toc'])}


def test_find_archive_addon_tocs_accepts_multitoc():
    assert {h for _, h in find_archive_addon_tocs(['a', 'a/a_mainline.toc'])} == {'a'}


@pytest.mark.parametrize('ext', product('Tt', 'Oo', 'Cc'))
def test_find_archive_addon_tocs_toc_is_case_insensitive(ext: tuple[str, ...]):
    assert {h for _, h in find_archive_addon_tocs([f'a/a.{"".join(ext)}'])} == {'a'}


def test_make_archive_member_filter_fn_discards_names_with_prefix_not_in_dirs():
    is_member = make_archive_member_filter_fn({'b'})
    assert list(filter(is_member, ['a/', 'b/', 'aa/', 'bb/', 'b/c', 'a/d'])) == ['b/', 'b/c']
