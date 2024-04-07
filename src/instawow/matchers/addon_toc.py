from __future__ import annotations

from collections.abc import Iterator, Mapping
from functools import cached_property
from pathlib import Path

from typing_extensions import Self


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
    def from_path(cls, path: Path) -> Self:
        return cls(path.read_text(encoding='utf-8-sig', errors='replace'))

    @cached_property
    def interfaces(self) -> list[int]:
        interface = self.get('Interface')
        return list(map(int, interface.split(','))) if interface else []
