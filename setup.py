from pathlib import Path

from setuptools import find_packages, setup


setup(name='instawow',
      url='http://github.com/layday/instawow',
      author='layday',
      author_email='layday@protonmail.com',
      license='GPL-3.0-or-later',
      description='CLI for managing World of Warcraft add-ons',
      long_description=Path('README.rst').read_text(encoding='utf-8'),
      entry_points={'console_scripts': ['instawow = instawow.cli:main']},
      install_requires='''aiohttp>=3.3,<4
                          alembic>=1,<2
                          click>=7,<8
                          fuzzywuzzy
                          jinja2>=2,<3
                          loguru
                          lupa
                          prompt-toolkit>=2,<3
                          pydantic~=1.4.0
                          questionary==1.3.0
                          SQLAlchemy>=1,<2
                          yarl>=1,<2''',
      extras_require={":python_version < '3.8'": '''importlib-metadata>=1,<2
                                                    typing-extensions'''},
      python_requires='~=3.7',
      include_package_data=True,
      packages=find_packages())
