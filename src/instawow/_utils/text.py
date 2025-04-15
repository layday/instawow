from __future__ import annotations

from collections.abc import Callable, Sequence


def tabulate(rows: Sequence[tuple[object, ...]], *, max_col_width: int = 60) -> str:
    "Produce an ASCII table from equal-length elements in a sequence."

    from functools import partial
    from textwrap import fill

    from wcwidth import wcswidth

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
    import string

    trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

    def normalise(value: str):
        return replace_delim.join(value.casefold().translate(trans_table).split())

    return normalise
