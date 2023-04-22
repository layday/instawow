# These tests are adapted from SLPP <https://github.com/SirAnthony/slpp>.
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

import pytest

from instawow._custom_slpp import ParseError, loads


def test_numbers():
    # int and float
    assert loads('3') == 3
    assert loads('3.') == 3
    assert loads('3.1') == 3.1
    # negative float
    assert loads('-0.45') == -0.45
    # scientific
    assert loads('3e-07') == 3e-7
    assert loads('-3.23e+17') == -3.23e17
    # hex
    assert loads('0x3a') == 0x3A
    assert (
        loads(
            '''{
                ID = 0x74fa4cae,
                Version = 0x07c2,
                Manufacturer = 0x21544948
            }'''
        )
        == {'ID': 0x74FA4CAE, 'Version': 0x07C2, 'Manufacturer': 0x21544948}
    )


def test_bool():
    assert loads('true') is True
    assert loads('false') is False
    assert loads('falser') == 'falser'


def test_nil():
    assert loads('nil') is None


def test_string_with_and_without_escape():
    assert loads("'test\\'s string'") == "test's string"
    assert loads('"test\\\'s string"') == "test\\'s string"
    assert loads('"test\'s string"') == "test's string"
    assert loads("[[test\\'s string]]") == "test\\'s string"
    assert loads("[[test's string]]") == "test's string"
    # https://github.com/SirAnthony/slpp/issues/23
    assert loads("'--3'") == '--3'


def test_array_like_table():
    # keyword values
    assert loads('{ false, true }') == [False, True]
    # nil is erased
    assert loads('{ nil }') == {}
    # string literals
    assert loads('{ "10" }') == ['10']
    # trailing zero
    assert loads('{ 0, 1, 0 }') == [0, 1, 0]


def test_dict_like_table():
    # bracketed keyword keys
    assert loads('{ [10] = 11 }') == {10: 11}
    assert loads('{ [false] = 0 }') == {False: 0}
    assert loads('{ [true] = 1 }') == {True: 1}
    # bracketed string keys
    assert loads('{ [ [[10]] ] = 1 }') == {'10': 1}
    assert loads('{ [ [[false]] ] = "" }') == {'false': ''}
    # syntax error
    with pytest.raises(ParseError):
        loads('{ [[false]] = "" }')


def test_boolean_keys_are_not_numeric():
    assert loads('{ [false] = "", [true] = "" }') == {False: '', True: ''}
    assert loads('{ [false] = "", [true] = "", [3] = "" }') == {False: '', True: '', 3: ''}


def test_table_key_overrides():
    assert loads(
        '{ 43, 54.3, false, string = "value", 9, [4] = 111, [1] = 222, [2.1] = "text" }'
    ) == {
        1: 43,
        2: 54.3,
        3: False,
        4: 9,
        'string': 'value',
        2.1: 'text',
    }
    assert loads('{ 43, 54.3, false, 9, [5] = 111, [7] = 222 }') == {
        1: 43,
        2: 54.3,
        3: False,
        4: 9,
        5: 111,
        7: 222,
    }
    assert loads('{ [7] = 111, [5] = 222, 43, 54.3, false, 9 }') == {
        7: 111,
        5: 222,
        1: 43,
        2: 54.3,
        3: False,
        4: 9,
    }
    assert loads('{ 43, 54.3, false, 9, [4] = 111, [5] = 52.1 }') == [
        43,
        54.3,
        False,
        9,
        52.1,
    ]
    assert loads('{ [5] = 111, [4] = 52.1, 43, [3] = 54.3, false, 9 }') == {
        5: 111,
        4: 52.1,
        1: 43,
        2: False,
        3: 9,
    }
    assert loads('{ [1] = 1, [2] = "2", 3, 4, [5] = 5, [5] = 6 }') == {
        1: 3,
        2: 4,
        5: 6,
    }


def test_table_palooza():
    assert (
        loads(
            '''{ -- δκσξδφξ
        array = { 65, 23, 5 }, -- 3493
        dict =     {  -- !!!,11
            [false]       =    "value"      ,  -- what's up
            ["array"] = {  -- waddup
                3, [[6]],   -- wassup
                4 }, -- [2]
            mixed = { 43, 54.3, false, string = "value", 9 }    -- wazzup
        }                   -- foo
} -- bar'''
        )
        == {
            'array': [65, 23, 5],
            'dict': {
                False: 'value',
                'array': [3, '6', 4],
                'mixed': {1: 43, 2: 54.3, 3: False, 'string': 'value', 4: 9},
            },
        }
    )


def test_parse_undelimited_entries():
    # Not valid Lua but we allow it for the purpose of parsing saved var scripts
    # containing more than one variable.
    assert (
        loads(
            '''{
                foo = {}
                bar = 1
            }'''
        )
        == {
            'foo': {},
            'bar': 1,
        }
    )
