from __future__ import annotations


def _patch_loguru() -> None:
    import queue
    import threading
    from types import SimpleNamespace

    import loguru._handler

    # On *nix instantiating multiprocessing constructs starts
    # the resource monitor.  This is done in a subprocess
    # with `sys.executable` as the first argument.  In briefcase
    # this points to the same executable that starts the app; there
    # isn't a separate Python executable; so with every new resource
    # monitor that spawns so does a new copy of the app, ad infinitum.
    # We replace these multiprocessing constructs with their threading
    # equivalents in loguru since loguru itself does not spawn a subprocesses
    # but creates a separate thread for its "enqueued" logger.
    # This will definitely not come back to bite us.

    loguru._handler.multiprocessing = SimpleNamespace(
        SimpleQueue=queue.Queue,
        Event=threading.Event,
        Lock=threading.Lock,
    )


def _patch_aiohttp() -> None:
    from functools import partial
    import ssl

    import aiohttp
    import certifi

    # SSL is misconfigured on the briefcase Python.  Instead of trying
    # to fix the paths, let's just use certifi.
    # See: https://github.com/beeware/Python-Apple-support/issues/119

    original_aiohttp_TCPConnector = aiohttp.TCPConnector
    aiohttp.TCPConnector = partial(
        original_aiohttp_TCPConnector,
        ssl=ssl.create_default_context(cafile=certifi.where()),
    )


def _patch_std_streams() -> None:
    import io
    import sys

    # These are ``None`` when pythonw is used.
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = io.StringIO()


def _running_under_briefcase() -> bool:
    import sys

    # We don't use Python < 3.8 with briefcase.  If we can't import
    # ``importlib.metadata`` then we're not in briefcase.
    if sys.version_info > (3, 7):
        import importlib.metadata

        try:
            return importlib.metadata.distribution(__package__) and True
        except importlib.metadata.PackageNotFoundError:
            return False

    else:
        return False


def main() -> None:
    import sys

    import instawow.cli

    if _running_under_briefcase():
        _patch_std_streams()
        _patch_loguru()
        _patch_aiohttp()

        # ``click`` doesn't run without previously printing something to stdout,
        # presumably something to do with spooling.
        print()

    instawow.cli.main(sys.argv[1:] or ['gui'])


if __name__ == '__main__':
    main()
