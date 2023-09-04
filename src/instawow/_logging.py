from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


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

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=log_level, force=True)


def setup_logging(
    logging_dir: Path, log_to_stderr: bool, debug: bool, intercept_logging_module_calls: bool
) -> None:
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
