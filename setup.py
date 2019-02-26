
from pathlib import Path
from setuptools import setup

try:
    import fastentrypoints
except ImportError:
    pass

from instawow import __version__


setup(name='instawow',
      version=__version__,
      description='A CLI for managing World of Warcraft add-ons.',
      url='http://github.com/layday/instawow',
      author='layday',
      author_email='layday@protonmail.com',
      license='GPL-3.0-or-later',
      long_description=Path('README.rst').read_text(),
      python_requires='~=3.7',
      packages=['instawow'],
      install_requires=Path('requirements.txt').read_text(),
      include_package_data=True,
      entry_points={'console_scripts': ['instawow = instawow.cli:cli']})
