from __future__ import annotations

import string
from collections.abc import Callable, Sequence


def tabulate(rows: Sequence[tuple[object, ...]], *, max_col_width: int = 60) -> str:
    "Produce an ASCII table from equal-length elements in a sequence."
    from textwrap import fill

    def apply_max_col_width(value: object):
        return fill(str(value), width=max_col_width, max_lines=1)

    def calc_resultant_col_widths(rows: Sequence[tuple[str, ...]]):
        cols = zip(*rows)
        return [max(map(len, c)) for c in cols]

    norm_rows = [tuple(apply_max_col_width(i) for i in r) for r in rows]
    head, *tail = norm_rows

    base_template = '  '.join(f'{{{{{{0}}{w}}}}}' for w in calc_resultant_col_widths(norm_rows))
    row_template = base_template.format(':<')
    table = '\n'.join(
        (
            base_template.format(':^').format(*head),
            base_template.format('0:-<').format(''),
            *(row_template.format(*r) for r in tail),
        )
    )
    return table


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
