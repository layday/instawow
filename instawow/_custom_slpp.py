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

from itertools import count, dropwhile
from operator import eq
import re
import string

whitespace = string.whitespace
newline = '\r\n'
keywords = {'true': True, 'false': False, 'nil': None}

match_identifier = re.compile(r'^[a-z_]\w*$', flags=re.IGNORECASE)


class ParseError(Exception):
    pass


class _Sentinel(str):
    pass


_sentinel = _Sentinel()


class SLPP:
    def __init__(self, text: str):
        self.iter_text = iter(text)

    def decode(self):
        self.next()
        return self.get_value()

    def next(self):
        self.c = next(self.iter_text, _sentinel)

    def next_nl(self):
        self.c = next(dropwhile(lambda c: c not in newline, self.iter_text), _sentinel)

    def this_or_next_not_ws(self):
        if self.c in whitespace:
            self.c = next(dropwhile(whitespace.__contains__, self.iter_text), _sentinel)

    def get_value(self):
        self.this_or_next_not_ws()
        if not self.c:
            raise ParseError('input is empty')

        if self.c == '{':
            return self.get_table()
        elif self.c == '[':
            self.next()

        if self.c in '\'"[':
            return self.get_string()
        elif self.c == '-' or self.c.isdigit():
            return self.get_number()
        return self.get_bare_word()

    def get_table(self):
        table = {}
        idx = 0

        self.next()
        while True:
            self.this_or_next_not_ws()

            if self.c == '}':

                # Convert table to list if k(0) = 1 and k = k(n-1) + 1, ...
                if (
                    table
                    and all(map(eq, table, count(1)))
                    # bool is a subclass of int in Python but not in Lua
                    and not any(isinstance(k, bool) for k in table)
                ):
                    table = list(table.values())

                self.next()
                return table

            elif self.c == ',':

                self.next()

            else:

                item = self.get_value()
                # Item is either a key or a string literal (this needs to be handled better)
                if self.c == ']':
                    self.next()

                self.this_or_next_not_ws()
                c = self.c
                if c in '=,':
                    self.next()
                    if c == '=':
                        # nil key produces a runtime error in Lua
                        if item is None:
                            raise ParseError('table keys cannot be nil')

                        # Item is a key
                        value = self.get_value()
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

    def get_string(self):
        s = ''
        start = self.c
        end = ']' if start == '[' else start
        for self.c in self.iter_text:
            if self.c == end:
                self.next()
                return s
            if self.c == '\\' and start == end:
                self.next()
                if self.c != end:
                    s += '\\'
            s += self.c

    def get_bare_word(self):
        s = self.c
        for self.c in self.iter_text:
            new_s = s + self.c
            if match_identifier.match(new_s):
                s = new_s
            else:
                break
            if s in keywords:
                break
        self.next()
        return keywords.get(s, s)

    def get_number(self):
        n = ''
        if self.c == '-':
            c = self.c
            self.next()
            if self.c == '-':
                # This is a comment - skip to the end of the line
                self.next_nl()
                return None
            elif not self.c or not self.c.isdigit():
                raise ParseError('malformed number (no digits after initial minus)', c, self.c)
            n += c
        n += self.get_digit()
        if n == '0' and self.c in 'Xx':
            n += self.c
            self.next()
            n += self.get_hex()
        else:
            if self.c and self.c == '.':
                n += self.c
                self.next()
                n += self.get_digit()
            if self.c and self.c in 'Ee':
                n += self.c
                self.next()
                if not self.c or self.c not in '+-':
                    raise ParseError('malformed number (bad scientific format)', n, self.c)
                n += self.c
                self.next()
                if not self.c.isdigit():
                    raise ParseError('malformed number (bad scientific format)', n, self.c)
                n += self.get_digit()
        try:
            return int(n, 0)
        except BaseException:
            pass
        return float(n)

    def get_digit(self):
        n = ''
        while self.c and self.c.isdigit():
            n += self.c
            self.next()
        return n

    def get_hex(self):
        n = ''
        while self.c and (self.c in 'ABCDEFabcdef' or self.c.isdigit()):
            n += self.c
            self.next()
        return n


def decode(text: str):
    return SLPP(text).decode()
