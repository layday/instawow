from __future__ import annotations

import multiprocessing
import os
import sys

from loguru import logger as logger

_logs_state_name = '_logs_v1'


def _intercept_logging_module_calls(log_level: str):  # pragma: no cover
    import inspect
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
            depth = 0
            frame = inspect.currentframe()
            while frame and (depth == 0 or frame.f_code.co_filename == logging_filename):
                frame = frame.f_back
                depth += 1

            logger.bind(source='logging').opt(depth=depth, exception=record.exc_info).log(
                level, record.getMessage()
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=log_level, force=True)


def setup_logging(
    parent_dir: os.PathLike[str],
    log_to_stderr: bool,
    debug: bool,
    intercept_logging_module_calls: bool,
    *,
    profile: str,
) -> None:
    log_level = 'DEBUG' if debug else 'INFO'

    if intercept_logging_module_calls:
        _intercept_logging_module_calls(log_level)

    context = None
    if sys.platform == 'darwin' and 'fork' in multiprocessing.get_all_start_methods():
        # Avoid the overhead of starting the "spawn" method's resource tracker.
        # instawow doesn't use multi-processing at all and neither does loguru;
        # it simply creates MP sync primitives to support applications that do.
        # When `enqueue` is `True`, messages are logged in a sub-thread of the
        # main process and not in a separate process.
        context = multiprocessing.get_context('fork')

    handlers = [
        {
            'level': log_level,
            'format': (
                '<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</> | '
                '<level>{level: <8}</> | '
                '{extra[profile]: <10} | '
                '<cyan>{name}</>:<cyan>{function}</>:<cyan>{line}</> | '
                '<level>{message}</>'
            ),
            'enqueue': True,
            'context': context,
            'sink': os.path.join(parent_dir, _logs_state_name, 'debug.log'),
            'rotation': '5 MB',
            'retention': 5,  # Number of log files to keep
        },
    ]
    if log_to_stderr:
        handlers += [
            {
                'level': log_level,
                'format': '<level>{level: <8}</> {name}:{line}\n<dim>{message}</>',
                'enqueue': True,
                'context': context,
                'sink': sys.stderr,
            },
        ]

    logger.configure(
        extra={'profile': profile},
        handlers=handlers,  # pyright: ignore[reportArgumentType]
    )
