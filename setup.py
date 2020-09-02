from pathlib import Path

from setuptools import find_packages, setup

setup(
    name='instawow',
    url='http://github.com/layday/instawow',
    author='layday',
    author_email='layday@protonmail.com',
    license='GPL-3.0-or-later',
    description='CLI for managing World of Warcraft add-ons',
    long_description=Path('README.rst').read_text(encoding='utf-8'),
    entry_points={'console_scripts': ['instawow = instawow.cli:main']},
    install_requires='''
        aiohttp           ~=3.5
        alembic           ~=1.4
        click             ~=7.1
        jellyfish         ~=0.8.2
        jinja2            ~=2.11
        loguru            <1
        prompt-toolkit    >=3, !=3.0.0, !=3.0.1, !=3.0.2, <4
        pydantic          ~=1.6.1
        questionary       >=1, !=1.3.0, <2
        slpp              ==1.2.1
        sqlalchemy        ~=1.3
        typing-extensions ~=3.7
        yarl              ~=1.4
    ''',
    extras_require={
        'server': '''
            aiohttp-rpc == 0.6.2
        ''',
        'test': '''
            coverage[toml]   ~=5.0
            pytest           >=6.0.1, <7
            pytest-asyncio   ~=0.14
            aresponses       ~=2.0
            sqlalchemy-stubs
        ''',
    },
    python_requires='~=3.7',
    include_package_data=True,
    packages=find_packages(),
)
