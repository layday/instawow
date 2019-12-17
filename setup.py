from pathlib import Path

from setuptools import find_packages, setup


metadata = {
    'name': 'instawow',
    'url': 'http://github.com/layday/instawow',
    'author': 'layday',
    'author_email': 'layday@protonmail.com',
    'license': 'GPL-3.0-or-later',
    'description': 'A CLI for managing World of Warcraft add-ons.',
    'long_description': Path('README.rst').read_text(encoding='utf-8'),}

options = {
    'entry_points': {'console_scripts': ['instawow = instawow.cli:main']},
    'install_requires': Path('requirements.txt').read_text(),
    'python_requires': '~=3.7',
    'include_package_data': True,
    'packages': find_packages(),
    'use_scm_version': True,}

setup(**metadata, **options)
