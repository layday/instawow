from functools import partial
import os
from pathlib import Path
from setuptools import find_packages, setup

if os.environ.get('INSTAWOW_DEV'):
    import fastentrypoints


read_text = partial(Path.read_text, encoding='utf-8')


setup(name='instawow',
      use_scm_version={'write_to': 'instawow/_version.py',
                       'write_to_template': "__version__ = '{version}'\n",},
      description='A CLI for managing World of Warcraft add-ons.',
      url='http://github.com/layday/instawow',
      author='layday',
      author_email='layday@protonmail.com',
      license='GPL-3.0-or-later',
      long_description=read_text(Path('README.rst')),
      python_requires='~=3.7',
      packages=find_packages(),
      setup_requires='setuptools_scm',
      install_requires=read_text(Path('requirements.txt')),
      include_package_data=True,
      entry_points={'console_scripts': ['instawow = instawow.cli:main']},)
