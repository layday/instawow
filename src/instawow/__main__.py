import sys

from instawow.cli import main

if __name__ == '__main__':
    prog_name = sys.executable if getattr(sys, 'frozen', False) else None
    main(prog_name=prog_name)
