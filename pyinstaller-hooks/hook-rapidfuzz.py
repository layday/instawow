from PyInstaller.utils.hooks import collect_submodules as _collect_submodules

hiddenimports = _collect_submodules('rapidfuzz') + _collect_submodules('jarowinkler')
