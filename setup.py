
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
      python_requires='~=3.7',
      packages=['instawow'],
      install_requires=['aiohttp==3.5.4',
                        'click==7.0',
                        'jinja2==2.10',
                        'Logbook==1.4.3',
                        'luaparser==2.1.2',
                        'parsel==1.5.1',
                        'pydantic==0.19',
                        'Send2Trash==1.5.0',
                        'SQLAlchemy==1.2.17',
                        'texttable==1.6.0',
                        'tqdm==4.31.1',
                        'uvloop==0.12.1; platform_system != "Windows"',
                        'yarl==1.3.0'],
      package_data={'instawow': ['assets/*',
                                 'wa_templates/*']},
      entry_points={'console_scripts': ['instawow = instawow.cli:cli']})
