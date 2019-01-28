
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
      python_requires='~=3.6',
      packages=['instawow'],
      install_requires=['aiohttp==3.5.4',
                        'click==7.0',
                        'contextvars==2.3; python_version < "3.7"',
                        'Logbook==1.4.3',
                        'parsel==1.5.1',
                        'pydantic==0.18.2',
                        'Send2Trash==1.5.0',
                        'SQLAlchemy==1.2.16',
                        'texttable==1.6.0',
                        'tqdm==4.29.1',
                        'yarl==1.3.0',
                        'uvloop==0.12.0; platform_system != "Windows"',],
      package_data={'instawow': ['assets/*']},
      entry_points={'console_scripts': ['instawow = instawow.cli:cli']})
