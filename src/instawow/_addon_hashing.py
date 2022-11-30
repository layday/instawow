from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

from loguru import logger

_TOC_FILE_PATH_PATTERN = re.compile(
    r'^(?P<name>[^/]+)/(?P=name)(?:[-_](?:mainline|bcc|tbc|classic|vanilla|wrath|wotlkc))?\.toc$',
    flags=re.I,
)
_BINDINGS_XML_FILE_PATH_PATTERN = re.compile(
    r'^[^/]+/Bindings\.xml$',
    flags=re.I,
)
_TOC_COMMENT_PATTERN = re.compile(
    r'\s*#.*$',
    flags=re.I | re.M,
)
_XML_COMMENT_PATTERN = re.compile(
    r'<!--.*?-->',
    flags=re.I | re.S,
)
_TOC_INCLUDE_PATTERN = re.compile(
    r'^\s*(?P<path>(?:(?<!\.\.).)+\.(?:xml|lua))\s*$',
    flags=re.I | re.M,
)
_XML_INCLUDE_PATTERN = re.compile(
    r"<(?:Include|Script)\s+file=[\"'](?P<path>(?:(?<!\.\.).)+)[\"']\s*\/>",
    flags=re.I,
)

_INCLUDE_FILE_PATTERNS = {
    '.toc': (_TOC_COMMENT_PATTERN, _TOC_INCLUDE_PATTERN),
    '.xml': (_XML_COMMENT_PATTERN, _XML_INCLUDE_PATTERN),
}


def _scan_addon_folder(folder: Path, root_folder: Path) -> Iterator[Path]:
    for entry in map(Path, os.scandir(folder)):
        relative_posix_path = entry.relative_to(root_folder).as_posix()
        if _TOC_FILE_PATH_PATTERN.match(relative_posix_path):
            yield from _scan_includes(entry)
        elif _BINDINGS_XML_FILE_PATH_PATTERN.match(relative_posix_path):
            yield entry
        elif entry.is_dir():
            yield from _scan_addon_folder(entry, root_folder)


def _scan_includes(file_path: Path) -> Iterator[Path]:
    if not file_path.exists():
        logger.debug(f'{file_path} does not exist')
        return

    yield file_path

    lower_suffix = file_path.suffix.casefold()
    try:
        comment_pattern, include_pattern = _INCLUDE_FILE_PATTERNS[lower_suffix]
    except KeyError:
        return

    contents = file_path.read_text(encoding='utf-8-sig', errors='replace')
    contents_without_comments = comment_pattern.sub('', contents)
    matches = (
        m.group('path').replace('\\', os.sep).strip()
        for m in include_pattern.finditer(contents_without_comments)
    )
    for match in matches:
        yield from _scan_includes(file_path.parent / match)


def _md5hash_bytes(value: bytes):
    return hashlib.md5(value, usedforsecurity=False).hexdigest()


def _md5hash_file(path: Path):
    return _md5hash_bytes(path.read_bytes())


def _md5hash_hashes(value: Iterator[str]):
    return _md5hash_bytes(''.join(sorted(value)).encode())


@lru_cache
def generate_wowup_addon_hash(path: Path):
    files_to_hash = frozenset(_scan_addon_folder(path, path.parent))
    combined_hash = _md5hash_hashes(_md5hash_file(f) for f in files_to_hash)
    logger.debug(f'calculated {combined_hash} for {path.name}')
    return combined_hash
