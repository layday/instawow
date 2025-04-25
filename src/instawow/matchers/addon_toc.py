from __future__ import annotations

from collections.abc import Iterator, Mapping
from functools import cached_property
from pathlib import Path
from typing import Self


class TocReader(Mapping[str, str]):
    """Extracts key-value pairs from TOC files."""

    def __init__(self, contents: str) -> None:
        self._entries = {
            k: v
            for e in contents.splitlines()
            if e.startswith('##')
            for k, v in (map(str.strip, e.lstrip('#').partition(':')[::2]),)
            if k
        }

    def __iter__(self) -> Iterator[str]:
        return iter(self._entries)

    def __getitem__(self, key: str, /) -> str:
        return self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)

    @classmethod
    def from_bytes(cls, content: bytes) -> Self:
        return cls(content.decode(encoding='utf-8-sig', errors='replace'))

    @classmethod
    def from_path(cls, path: Path) -> Self:
        return cls.from_bytes(path.read_bytes())

    @cached_property
    def interfaces(self) -> list[int]:
        return [int(i) for i in self.get('Interface', '').split(',') if i]

    @cached_property
    def version(self) -> str:
        return self.get('Version', '')
