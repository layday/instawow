from __future__ import annotations

import sys


def _make_getattr(package_name: str):
    import importlib.util

    def __getattr__(name: str):
        """Defer importing own modules until attempting to access an attribute.

        Importing this in ``__init__`` will overwrite relative imports.
        """
        fullname = package_name + '.' + name

        try:
            return sys.modules[fullname]
        except KeyError:
            spec = importlib.util.find_spec(fullname)
            if spec is None or spec.loader is None:
                # ``AttributeError`` is converted to an ``ImportError`` by the import machinery.
                raise AttributeError from None

            spec.loader = loader = importlib.util.LazyLoader(spec.loader)
            sys.modules[fullname] = module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)

            return module

    return __getattr__


def main():

    if sys.version_info >= (3, 15):
        sys.set_lazy_imports('all')

        @sys.set_lazy_imports_filter
        def _(
            importing_module: str | None, imported_module: str, fromlist: tuple[str, ...] | None
        ):
            return importing_module not in {
                'truststore',
            }

    else:
        import instawow

        instawow.__getattr__ = _make_getattr(instawow.NAME)

    from instawow.cli import main as main_

    main_()


if __name__ == '__main__':
    main()
