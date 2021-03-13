# This module is adapted from SLPP <https://github.com/SirAnthony/slpp>.
#
#   Copyright (c) 2010, 2011, 2012 SirAnthony <anthony at adsorbtion.org>
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy
#   of this software and associated documentation files (the "Software"), to deal
#   in the Software without restriction, including without limitation the rights
#   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is
#   furnished to do so, subject to the following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
#   THE SOFTWARE.

from __future__ import annotations

from itertools import count, dropwhile, islice
from operator import eq
import re
import string
from typing import Any

WHITESPACE = frozenset(string.whitespace)
NEWLINE = frozenset('\r\n')
KEYWORDS = {'true': True, 'false': False, 'nil': None}

match_bare_word = re.compile(r'^[a-z_]\w*$', flags=re.IGNORECASE)


class ParseError(Exception):
    pass


class _Sentinel(str):
    pass


_sentinel = _Sentinel()


class SLPP:
    def __init__(self, text: str):
        self.iter_text = iter(text)

    def decode(self):
        self._next()
        return self._get_value()

    def _next(self):
        self.c = next(self.iter_text, _sentinel)

    def _next_not(self, exclude: frozenset[str] | str):
        if self.c in exclude:
            self.c = next(dropwhile(exclude.__contains__, self.iter_text), _sentinel)

    def _next_nl(self):
        self.c = next((c for c in self.iter_text if c in NEWLINE), _sentinel)

    def _get_value(self):
        self._next_not(WHITESPACE)
        if not self.c:
            raise ParseError('input is empty')
        elif self.c == '{':
            return self._get_table()
        elif self.c in '\'"[':
            return self._get_string()
        elif self.c == '-' or self.c.isdigit():
            return self._get_number()
        else:
            return self._get_bare_word()

    def _get_table(self) -> dict[Any, Any] | list[Any]:
        table: dict[Any, Any] | list[Any] = {}
        idx = 0

        self._next()
        while True:
            self._next_not(WHITESPACE)

            if self.c == '}':

                # Convert table to list if k(0) = 1 and k = k(n-1) + 1, ...
                if (
                    table
                    and all(map(eq, table, count(1)))
                    # bool is a subclass of int in Python but not in Lua
                    and not any(isinstance(k, bool) for k in islice(table, 0, 2))
                ):
                    table = list(table.values())

                self._next()
                return table

            elif self.c == ',':

                self._next()

            else:

                is_val_long_string_literal = False

                if self.c == '[':
                    self._next()
                    if self.c == '[':
                        is_val_long_string_literal = True

                item = self._get_value()
                self._next_not(WHITESPACE | {']'})

                c = self.c
                if c in '=,':
                    self._next()

                    if c == '=':
                        if is_val_long_string_literal:
                            raise ParseError('malformed key', item)

                        # nil key produces a runtime error in Lua
                        if item is None:
                            raise ParseError('table keys cannot be nil')

                        # Item is a key
                        value = self._get_value()
                        if (
                            # nil values are not persisted in Lua tables
                            value is not None
                            # Where the key is a valid index key-less values take precedence
                            and (not isinstance(item, int) or isinstance(item, bool) or item > idx)
                        ):
                            table[item] = value
                        continue

                if item is not None:
                    idx += 1
                    table[idx] = item

    def _get_string(self):
        s = ''
        start = self.c
        if start == '[':
            self._next_not('[')
            s += self.c
            end = ']'
        else:
            end = start

        for self.c in self.iter_text:
            if self.c == end:
                break
            elif self.c == '\\' and start == end:
                self._next()
                if self.c != end:
                    s += '\\'
            s += self.c

        if start != end:
            self._next()
        else:
            # Strip multiple closing brackets
            self._next_not(end)
        return s

    def _get_bare_word(self):
        s = self.c
        for self.c in self.iter_text:
            new_s = s + self.c
            if match_bare_word.match(new_s):
                s = new_s
            else:
                break

        self._next()
        return KEYWORDS.get(s, s)

    def _get_number(self):
        n = ''

        if self.c == '-':
            c = self.c
            self._next()
            if self.c == '-':

                # This is a comment - skip to the end of the line
                self._next_nl()
                return None

            elif not self.c or not self.c.isdigit():

                raise ParseError('malformed number (no digits after initial minus)', c + self.c)

            n += c

        n += self._get_digit()
        if n == '0' and self.c in 'Xx':

            n += self.c
            self._next()
            n += self._get_hex()

        else:

            if self.c and self.c == '.':
                n += self.c
                self._next()
                n += self._get_digit()

            if self.c and self.c in 'Ee':
                n += self.c

                self._next()
                if not self.c or self.c not in '+-':
                    raise ParseError('malformed number (bad scientific format)', n, self.c)
                n += self.c

                self._next()
                if not self.c.isdigit():
                    raise ParseError('malformed number (bad scientific format)', n, self.c)
                n += self._get_digit()

        try:
            return int(n, 0)
        except Exception:
            return float(n)

    def _get_digit(self):
        n = ''
        while self.c and self.c.isdigit():
            n += self.c
            self._next()
        return n

    def _get_hex(self):
        n = ''
        while self.c and (self.c in 'ABCDEFabcdef' or self.c.isdigit()):
            n += self.c
            self._next()
        return n


def decode(text: str):
    return SLPP(text).decode()
