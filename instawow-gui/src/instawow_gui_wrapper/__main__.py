from __future__ import annotations


def _patch_std_streams() -> None:
    import io
    import sys

    # These are ``None`` when pythonw is used.
    if sys.stdout is None or sys.stderr is None:
        sys.stdout = sys.stderr = io.StringIO()


def _apply_patches():
    _patch_std_streams()


def main() -> None:
    import sys

    import instawow.cli

    _apply_patches()

    # ``click`` doesn't run without having previously printed something to stdout,
    # presumably something to do with spooling.
    print()

    instawow.cli.main(sys.argv[1:] or ['plugins', 'gui'])


if __name__ == '__main__':
    main()
