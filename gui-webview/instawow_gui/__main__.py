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


def _running_under_briefcase() -> bool:
    try:
        import importlib.metadata
    except ImportError:
        # briefcase uses Python 3.9 which ships with ``importlib.metadata``.
        # If we can't import importlib.metadata then we're not under briefcase.
        return False

    try:
        gui_metadata = importlib.metadata.metadata('instawow_gui')
    except importlib.metadata.PackageNotFoundError:
        return False
    else:
        return 'Briefcase-Version' in gui_metadata


def main() -> None:
    import sys

    import instawow.cli

    if _running_under_briefcase():
        print('patching loguru')
        _patch_loguru()

    instawow.cli.main(sys.argv[1:] or ['gui'])


if __name__ == '__main__':
    main()
