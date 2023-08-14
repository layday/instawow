from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def _patch_loguru_enqueue():
    import queue
    import threading
    from types import SimpleNamespace

    import loguru._handler

    # On some systems when instantiating multiprocessing constructs Python
    # starts the multiprocessing resource monitor.  This is done in a subprocess
    # with ``sys.executable`` as the first argument.  In briefcase
    # this points to the same executable that starts the app - there
    # isn't a separate Python executable.  So with every new resource
    # monitor that spawns so does a new copy of the app, ad infinitum.
    # Even when not using briefcase spawning a subprocess slows down start-up,
    # not least because it imports a second copy of the ``site`` module.
    # We replace these multiprocessing constructs with their threading
    # equivalents in loguru since loguru itself does not spawn a subprocesses
    # but creates a separate thread for its "enqueued" logger and we don't
    # use multiprocessing in instawow.
    # This will definitely not come back to bite us.
    loguru._handler.multiprocessing = SimpleNamespace(  # pyright: ignore[reportPrivateImportUsage]
        SimpleQueue=queue.Queue, Event=threading.Event, Lock=threading.Lock
    )


def _intercept_logging_module_calls(log_level: str):  # pragma: no cover
    import logging

    logging_filename = getattr(logging, '__file__', None)

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            # Get the corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where the logged message originated
            depth = 6
            frame = sys._getframe(depth)  # pyright: ignore[reportPrivateUsage]
            while frame and frame.f_code.co_filename == logging_filename:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=log_level, force=True)


def setup_logging(
    logging_dir: Path, log_to_stderr: bool, debug: bool, intercept_logging_module_calls: bool
) -> None:
    _patch_loguru_enqueue()

    log_level = 'DEBUG' if debug else 'INFO'

    if intercept_logging_module_calls:
        _intercept_logging_module_calls(log_level)

    handlers = [
        {
            'level': log_level,
            'enqueue': True,
            'sink': logging_dir / 'error.log',
            'rotation': '5 MB',
            'retention': 5,  # Number of log files to keep
        },
    ]
    if log_to_stderr:
        handlers += [
            {
                'level': log_level,
                'enqueue': True,
                'sink': sys.stderr,
                'format': (
                    '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | '
                    '<level>{level: <8}</level> | '
                    '<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>\n'
                    '  <level>{message}</level>'
                ),
            }
        ]

    logger.configure(handlers=handlers)
