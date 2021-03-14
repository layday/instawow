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
    long_description_content_type='text/x-rst',
    entry_points={'console_scripts': ['instawow = instawow.cli:main']},
    install_requires='''
        aiohttp           >=3.7.4, <4
        alembic           >=1.4.3, <2
        click             ~=7.1
        jellyfish         >=0.8.2, <1
        jinja2            ~=2.11
        loguru            <1
        pluggy            ~=0.13
        prompt-toolkit    >=3.0.15, <4
        pydantic          ~=1.8
        questionary       ~=1.8
        sqlalchemy        >=1.3.19, <2
        typing-extensions >=3.7.4.3, <4
        yarl              ~=1.4
    ''',
    extras_require={
        'server': '''
        aiohttp-rpc      ==0.6.3
        ''',
        'test': '''
        aresponses       ~=2.0
        coverage[toml]   ~=5.2
        pytest           >=6.0.1, <7
        pytest-asyncio   ~=0.14
        ''',
        'types': '''
        sqlalchemy2-stubs
        ''',
    },
    python_requires='~=3.7',
    include_package_data=True,
    packages=find_packages(),
)
