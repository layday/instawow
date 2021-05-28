from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import setuptools
import toml


def _pep621_metadata_to_setup_kwargs(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'name': metadata['name'],
        'author': metadata['authors'][0]['name'],
        'author_email': metadata['authors'][0]['email'],
        'description': metadata['description'],
        'long_description': Path(metadata['readme']).read_text(encoding='utf-8'),
        'long_description_content_type': 'text-x/rst',
        'project_urls': metadata['urls'],
        'entry_points': {
            'console_scripts': [f'{k} = {v}' for k, v in metadata['scripts'].items()]
        },
        'python_requires': metadata['requires-python'],
        'install_requires': metadata['dependencies'],
        'extras_require': metadata['optional-dependencies'],
    }


if __name__ == '__main__':
    project_toml = toml.load(Path('pyproject.toml').open(encoding='utf-8'))
    setuptools.setup(
        **_pep621_metadata_to_setup_kwargs(project_toml['project']),
        package_dir={
            'instawow': 'src/instawow',
            'instawow_gui': 'gui-webview/src/instawow_gui',
        },
        packages=setuptools.find_packages('src', include=['instawow'])
        + setuptools.find_packages('gui-webview/src', include=['instawow_gui']),
        include_package_data=True,
    )
