from __future__ import annotations

import sys

from instawow.cli import main

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        import multiprocessing

        multiprocessing.freeze_support()

        # Ensure IDNA encoding is imported and available to sub-threads.
        # Ref: https://github.com/layday/instawow/issues/108
        ''.encode('idna')

        prog_name = sys.executable
    else:
        prog_name = None

    main(prog_name=prog_name)
