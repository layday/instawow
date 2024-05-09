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

import re
import string
from itertools import count, islice
from operator import eq
from typing import Any

DIGITS = frozenset(string.digits)
HEXDIGITS = frozenset(string.hexdigits)
HEXDELIMS = frozenset('Xx')
EXPONENTS = frozenset('Ee')
WHITESPACE = frozenset(string.whitespace)
WHITESPACE_OR_CLOSING_SQ_BR = WHITESPACE | frozenset(']')
NEWLINE = frozenset('\r\n')

bare_word_pattern = re.compile(r'^[a-z_]\w*$', flags=re.IGNORECASE)


class ParseError(Exception):
    pass


class _Parser:
    def __init__(self, text: str):
        self.t = iter(text)
        self.c = next(self.t, '')

    def _decode_table(self):
        table: dict[Any, Any] | list[Any] = {}
        idx = 0

        self.c = next(self.t)
        while True:
            if self.c in WHITESPACE:
                for c in self.t:
                    if c not in WHITESPACE:
                        self.c = c
                        break

            if self.c == '}':
                # Convert table to list if k(0) = 1 and k = k(n-1) + 1, ...
                if (
                    table
                    and all(map(eq, table, count(1)))
                    # bool is a subclass of int in Python but not in Lua
                    and not any(isinstance(k, bool) for k in islice(table, 0, 2))
                ):
                    table = list(table.values())

                self.c = next(self.t, '')
                return table

            elif self.c == ',':
                self.c = next(self.t)

            else:
                is_val_long_string_literal = False

                if self.c == '[':
                    self.c = next(self.t)
                    if self.c == '[':
                        is_val_long_string_literal = True

                item = self.decode()

                if self.c in WHITESPACE_OR_CLOSING_SQ_BR:
                    for c in self.t:
                        if c not in WHITESPACE_OR_CLOSING_SQ_BR:
                            self.c = c
                            break

                c = self.c
                if c and c in '=,':
                    self.c = next(self.t)

                    if c == '=':
                        if is_val_long_string_literal:
                            raise ParseError('malformed key', item)

                        # nil key produces a runtime error in Lua
                        if item is None:
                            raise ParseError('table keys cannot be nil')

                        # Item is a key
                        value = self.decode()
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

    def _decode_string(self):
        s = ''
        start = self.c
        end = None
        prev_was_slash = False

        if start == '[':
            for c in self.t:
                if c != '[':
                    self.c = c
                    break

            s += self.c
            end = ']'
        else:
            end = start

        for c in self.t:
            if prev_was_slash:
                prev_was_slash = False

                if c != end:
                    s += '\\'
            elif c == end:
                break
            elif c == '\\' and start == end:
                prev_was_slash = True
                continue

            s += c

        self.c = next(self.t, '')
        if start != end:
            # Strip multiple closing brackets
            if self.c == end:
                for c in self.t:
                    if c != end:
                        self.c = c
                        break

        return s

    def _decode_bare_word(self):
        s = self.c
        for c in self.t:
            new_s = s + c
            if bare_word_pattern.match(new_s):
                s = new_s
            else:
                break

        self.c = next(self.t, '')

        match s:
            case 'true':
                return True
            case 'false':
                return False
            case 'nil':
                return None
            case _:
                return s

    def _decode_number(self):
        def get_digits():
            n = ''

            for c in self.t:
                if c in DIGITS:
                    n += c
                else:
                    self.c = c
                    break

            return n

        n = ''

        if self.c == '-':
            c = self.c
            self.c = next(self.t)
            if self.c == '-':
                # This is a comment - skip to the end of the line
                for c in self.t:
                    if c in NEWLINE:
                        self.c = c
                        break

                return None

            elif not self.c or self.c not in DIGITS:
                raise ParseError('malformed number (no digits after minus sign)', c + self.c)

            n += c

        n += self.c + get_digits()
        if n == '0' and self.c in HEXDELIMS:
            n += self.c

            for c in self.t:
                if c in HEXDIGITS:
                    n += c
                else:
                    self.c = c
                    break

        else:
            if self.c == '.':
                n += self.c + get_digits()

            if self.c in EXPONENTS:
                n += self.c
                self.c = next(self.t)  # +-
                n += self.c + get_digits()

        try:
            return int(n, 0)
        except ValueError:
            return float(n)

    def decode(self):
        if self.c in WHITESPACE:
            for c in self.t:
                if c not in WHITESPACE:
                    self.c = c
                    break

        if not self.c:
            raise ParseError('input is empty')

        if self.c == '{':
            return self._decode_table()
        elif self.c in '\'"[':
            return self._decode_string()
        elif self.c == '-' or self.c in DIGITS:
            return self._decode_number()
        else:
            return self._decode_bare_word()


def loads(s: str) -> Any:
    return _Parser(s).decode()
