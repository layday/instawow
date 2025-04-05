from __future__ import annotations

import string
from collections.abc import Callable, Sequence
from functools import partial
from textwrap import fill


def tabulate(rows: Sequence[tuple[object, ...]], *, max_col_width: int = 60) -> str:
    "Produce an ASCII table from equal-length elements in a sequence."

    from wcwidth import wcswidth  # pyright: ignore  # noqa: PGH003

    truncate = partial(fill, width=max_col_width, max_lines=1)

    def make_col_cells():
        for col in zip(*rows):
            col_cells = [(v, wcswidth(v)) for e in col for v in (truncate(str(e)),)]
            max_width = max(w for _, w in col_cells)
            yield [
                *((v, max_width - w) for v, w in col_cells[:1]),
                ('-' * max_width, 0),
                *((v, max_width - w) for v, w in col_cells[1:]),
            ]

    return '\n'.join('  '.join(f'{v}{" " * w}' for v, w in r) for r in zip(*make_col_cells()))


def normalise_names(replace_delim: str) -> Callable[[str], str]:
    trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

    def normalise(value: str):
        return replace_delim.join(value.casefold().translate(trans_table).split())

    return normalise


slugify = normalise_names('-')


def shasum(*values: object) -> str:
    "Base-16-encode a string using SHA-256 truncated to 32 characters."
    from hashlib import sha256

    return sha256(''.join(map(str, filter(None, values))).encode()).hexdigest()[:32]
