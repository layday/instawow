import sys

from instawow.cli import main

if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        import multiprocessing

        multiprocessing.freeze_support()

        prog_name = sys.executable
    else:
        prog_name = None

    main(prog_name=prog_name)
