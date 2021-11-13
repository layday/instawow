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

from instawow._custom_slpp import SLPP, ParseError


def decode(value: str):
    return SLPP(value).decode()


def test_numbers():
    # int and float
    assert decode('3') == 3
    assert decode('3.') == 3
    assert decode('3.1') == 3.1
    # negative float
    assert decode('-0.45') == -0.45
    # scientific
    assert decode('3e-07') == 3e-7
    assert decode('-3.23e+17') == -3.23e17
    # hex
    assert decode('0x3a') == 0x3A
    assert (
        decode(
            '''{
                ID = 0x74fa4cae,
                Version = 0x07c2,
                Manufacturer = 0x21544948
            }'''
        )
        == {'ID': 0x74FA4CAE, 'Version': 0x07C2, 'Manufacturer': 0x21544948}
    )


def test_bool():
    assert decode('true') == True
    assert decode('false') == False
    assert decode('falser') == 'falser'


def test_bool_keys_are_not_nums():
    assert decode('{ [false] = "", [true] = "" }') == {False: '', True: ''}
    assert decode('{ [false] = "", [true] = "", [3] = "" }') == {False: '', True: '', 3: ''}


def test_nil():
    decode('nil') == None


def test_simple_table():
    # bracketed key
    assert decode('{ [10] = 11 }') == {10: 11}
    assert decode('{ [false] = 0 }') == {False: 0}
    assert decode('{ [true] = 1 }') == {True: 1}
    # bracketed string key - not supported
    # assert decode('{ [ [[10]] ] = 1 }') == {"10": 1}
    # keywords in table
    assert decode('{ false, true }') == [False, True]
    # void table
    assert decode('{ nil }') == {}
    # values-only table
    assert decode('{ "10" }') == ["10"]
    # last zero
    assert decode('{ 0, 1, 0 }') == [0, 1, 0]


def test_string_with_and_without_escape():
    assert decode("'test\\'s string'") == "test's string"
    assert decode('"test\\\'s string"') == "test\\'s string"
    assert decode('"test\'s string"') == "test's string"
    assert decode("[[test\\'s string]]") == "test\\'s string"
    assert decode("[[test's string]]") == "test's string"
    # https://github.com/SirAnthony/slpp/issues/23
    assert decode("'--3'") == '--3'


def test_table_keys():
    assert decode('{ [ [[false]] ] = "" }') == {'false': ''}
    with pytest.raises(ParseError):
        decode('{ [[false]] = "" }')


def test_table_palooza():
    assert decode(
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
    ) == {
        'array': [65, 23, 5],
        'dict': {
            False: 'value',
            'array': [3, '6', 4],
            'mixed': {1: 43, 2: 54.3, 3: False, 'string': 'value', 4: 9},
        },
    }


def test_table_key_overrides():
    assert decode(
        '{ 43, 54.3, false, string = "value", 9, [4] = 111, [1] = 222, [2.1] = "text" }'
    ) == {
        1: 43,
        2: 54.3,
        3: False,
        4: 9,
        'string': 'value',
        2.1: 'text',
    }
    assert decode('{ 43, 54.3, false, 9, [5] = 111, [7] = 222 }') == {
        1: 43,
        2: 54.3,
        3: False,
        4: 9,
        5: 111,
        7: 222,
    }
    assert decode('{ [7] = 111, [5] = 222, 43, 54.3, false, 9 }') == {
        7: 111,
        5: 222,
        1: 43,
        2: 54.3,
        3: False,
        4: 9,
    }
    assert decode('{ 43, 54.3, false, 9, [4] = 111, [5] = 52.1 }') == [
        43,
        54.3,
        False,
        9,
        52.1,
    ]
    assert decode('{ [5] = 111, [4] = 52.1, 43, [3] = 54.3, false, 9 }') == {
        5: 111,
        4: 52.1,
        1: 43,
        2: False,
        3: 9,
    }
    assert decode('{ [1] = 1, [2] = "2", 3, 4, [5] = 5, [5] = 6 }') == {
        1: 3,
        2: 4,
        5: 6,
    }
