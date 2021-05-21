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

    original_aiohttp_TCPConnector = aiohttp.TCPConnector
    aiohttp.TCPConnector = partial(
        original_aiohttp_TCPConnector,
        ssl=ssl.create_default_context(cafile=certifi.where()),
    )


def _running_under_briefcase() -> bool:
    import sys

    # briefcase uses Python 3.9 which ships with ``importlib.metadata``.
    # If we can't import importlib.metadata then we're not under briefcase.
    if sys.version_info > (3, 7):
        import importlib.metadata

        try:
            gui_metadata = importlib.metadata.metadata('instawow_gui')
        except importlib.metadata.PackageNotFoundError:
            return False
        else:
            return 'Briefcase-Version' in gui_metadata

    else:
        return False


def main() -> None:
    import sys

    import instawow.cli

    if _running_under_briefcase():
        _patch_loguru()
        _patch_aiohttp()
        print()  # ``click`` doesn't run without this, for whatever reason.

    instawow.cli.main(sys.argv[1:] or ['gui'])


if __name__ == '__main__':
    main()
