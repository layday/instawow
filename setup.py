
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
      install_requires=['aiohttp==3.3.2',
                        'click==6.7',
                        'contextvars==2.2; python_version < "3.7"',
                        'outdated==0.1.2',
                        'parsel==1.4',
                        'pydantic==0.11.1',
                        'Send2Trash==1.5.0',
                        'SQLAlchemy==1.2.9',
                        'texttable==1.4.0',
                        'tqdm==4.23.4',
                        'yarl==1.2.6',
                        'uvloop==0.10.2; platform_system != "Windows"',],
      package_data={'instawow': ['assets/*']},
      entry_points={'console_scripts': ['instawow = instawow.cli:cli',
                                        'instawow-init = instawow.cli:init']})
