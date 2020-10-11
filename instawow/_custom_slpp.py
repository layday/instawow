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
keywords = {'true': True, 'false': False, 'nil': None}

match_identifier = re.compile(r'^[a-zA-Z_]\w*$')


class _ParseError(Exception):
    pass


_comment = object()


class _Sentinel(str):
    pass


_sentinel = _Sentinel()


class SLPP:
    def decode(self, text: str):
        self.iter_text = iter(text)
        self.depth = 0
        self.next_chr()
        return self.value()

    def next_chr(self):
        self.chr = next(self.iter_text, _sentinel)

    def this_or_next_chr_not_ws(self):
        if self.chr is not _sentinel and self.chr in whitespace:
            self.chr = next(dropwhile(whitespace.__contains__, self.iter_text))

    def value(self):
        self.this_or_next_chr_not_ws()
        if not self.chr:
            return _ParseError('input is empty')
        elif self.chr == '{':
            return self.table()
        if self.chr == '[':
            self.next_chr()
        if self.chr in '\'"[':
            return self.string()
        elif self.chr == '-' or self.chr.isdigit():
            return self.number()
        return self.word()

    def string(self):
        s = ''
        start = self.chr
        end = ']' if start == '[' else start
        while True:
            self.next_chr()
            if self.chr == end:
                self.next_chr()
                if start == end or self.chr == end:
                    return s
            if self.chr == '\\' and start == end:
                self.next_chr()
                if self.chr != end:
                    s += '\\'
            s += self.chr

    def table(self):
        o = {}
        k = None
        idx = count(1)
        self.depth += 1
        self.next_chr()
        self.this_or_next_chr_not_ws()
        if self.chr == '}':
            self.depth -= 1
            self.next_chr()
            return o
        else:
            while True:
                self.this_or_next_chr_not_ws()
                if self.chr == '{':
                    o[next(idx)] = self.table()
                    continue
                elif self.chr == '}':
                    self.depth -= 1
                    self.next_chr()
                    if k not in {None, _comment}:
                        o[next(idx)] = k

                    # Convert table to list if keys are sequential integers
                    # from 1 counting upwards
                    first_k = next(iter(o), None)
                    if first_k == 1 and all(map(eq, iter(o), count(1))):
                        o = list(o.values())
                    return o
                else:
                    if self.chr == ',':
                        self.next_chr()
                        continue
                    else:
                        k = self.value()
                        if self.chr == ']':
                            self.next_chr()

                    self.this_or_next_chr_not_ws()
                    c = self.chr
                    if c in '=,':
                        self.next_chr()
                        self.this_or_next_chr_not_ws()
                        if c == '=':
                            v = self.value()
                            # Key-less values take precedence
                            o.setdefault(k, v)
                        else:
                            o[next(idx)] = k
                        k = None

    def word(self):
        s = self.chr
        for self.chr in self.iter_text:
            new_s = s + self.chr
            if match_identifier.match(new_s):
                s = new_s
            else:
                break
            if s in keywords:
                break
        self.next_chr()
        return keywords.get(s, s)

    def number(self):
        def next_digit(err: str):
            c = self.chr
            self.next_chr()
            if not self.chr or not self.chr.isdigit():
                raise _ParseError(err, n, c, self.chr)
            return c

        n = ''
        if self.chr == '-':
            c = self.chr
            self.next_chr()
            if self.chr == '-':
                self.chr = next(dropwhile(lambda c: c not in '\r\n', self.iter_text))
                return _comment
            elif not self.chr or not self.chr.isdigit():
                raise _ParseError('malformed number (no digits after initial minus)', c, self.chr)
            n += c
        n += self.digit()
        if n == '0' and self.chr in 'Xx':
            n += self.chr
            self.next_chr()
            n += self.hex()
        else:
            if self.chr and self.chr == '.':
                n += self.chr
                self.next_chr()
                n += self.digit()
            if self.chr and self.chr in 'Ee':
                n += self.chr
                self.next_chr()
                if not self.chr or self.chr not in '+-':
                    raise _ParseError('malformed number (bad scientific format)', n, self.chr)
                n += next_digit('malformed number (bad scientific format)')
                n += self.digit()
        try:
            return int(n, 0)
        except:
            pass
        return float(n)

    def digit(self):
        n = ''
        while self.chr and self.chr.isdigit():
            n += self.chr
            self.next_chr()
        return n

    def hex(self):
        n = ''
        while self.chr and (self.chr in 'ABCDEFabcdef' or self.chr.isdigit()):
            n += self.chr
            self.next_chr()
        return n


slpp = SLPP()
