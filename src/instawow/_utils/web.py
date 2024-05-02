from __future__ import annotations

from pathlib import PurePath


def is_file_uri(uri: str) -> bool:
    return uri.startswith('file://')


def file_uri_to_path(file_uri: str) -> str:
    "Convert a file URI to a path that works both on Windows and *nix."
    from urllib.parse import unquote

    unprefixed_path = unquote(file_uri.removeprefix('file://'))
    # A slash is prepended to the path even when there isn't one there
    # on Windows.  The ``Path`` instance will inherit from either
    # ``PurePosixPath`` or ``PureWindowsPath``; this will be a no-op on POSIX.
    if PurePath(unprefixed_path[1:]).drive:
        unprefixed_path = unprefixed_path[1:]
    return unprefixed_path


def as_plain_text_data_url(body: str = '') -> str:
    from urllib.parse import quote

    return f'data:,{quote(body)}'


def extract_byte_range_offset(content_range: str) -> int:
    return int(content_range.replace('bytes ', '').partition('-')[0])


def open_url(url: str) -> None:
    import click

    click.launch(url)
