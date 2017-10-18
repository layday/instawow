
from pathlib import Path
from setuptools import setup

from instawow import __version__


setup(name='instawow',
      version=__version__,
      description='A CLI for managing World of Warcraft add-ons.',
      url='http://github.com/layday/instawow',
      author='layday',
      author_email='layday@protonmail.com',
      license='GPLv3',
      long_description=Path('README.rst').read_text(),
      classifiers=['Development Status :: 4 - Beta',
                   'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
                   'Programming Language :: Python :: 3.6'],
      python_requires='~=3.6',
      packages=['instawow'],
      install_requires=['aiohttp   >=2.3.0, <3',
                        'click     ~=6.7',
                        'pydantic  ==0.4',
                        'SQLAlchemy>=1.1.14,<2',
                        'texttable >=1.0.0, <2',
                        'yarl      >=0.13.0,<1'],
      extras_require={'uvloop': ['uvloop>=0.8.1']},
      package_data={'instawow': ['assets/*']},
      entry_points={'console_scripts': ['instawow = instawow.cli:cli',
                                        'instawow-init = instawow.cli:init']})
