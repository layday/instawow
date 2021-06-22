from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from textwrap import dedent

import nox

SUPPORTED_PYTHON_VERSIONS = ['3.7', '3.8', '3.9']


def _mirror_project(session: nox.Session):
    tmp_dir = session.create_tmp()
    session.run('git', 'clone', '.', tmp_dir, external=True)
    session.chdir(tmp_dir)


@nox.session(reuse_venv=True)
def reformat(session: nox.Session):
    "Reformat Python source code using Black and JavaScript using Prettier."
    session.install('isort >=5.8.0', 'black >=20.8b1')
    for cmd in ('isort', 'black'):
        session.run(
            cmd,
            'src',
            'gui-webview/src',
            'tests',
            'noxfile.py',
        )

    if '--skip-prettier' not in session.posargs:
        session.chdir('gui-webview/frontend')
        session.run(
            'npx',
            'prettier',
            '--write',
            'package.json',
            'rollup.config.js',
            'src',
            'tsconfig.json',
            external=True,
        )


@nox.session(python=SUPPORTED_PYTHON_VERSIONS)
@nox.parametrize(
    'constraints',
    [
        '',
        '''aiohttp ==3.7.4
           alembic ==1.4.3
           click ==7.1
           jinja2 ==2.11.0
           loguru ==0.1.0
           pluggy ==0.13.0
           prompt-toolkit ==3.0.15
           pydantic ==1.8.2
           questionary ==1.8.0
           rapidfuzz ==1.4.1
           sqlalchemy ==1.3.19
           typing-extensions ==3.10.0.0
           yarl ==1.4
           aiohttp-rpc ==0.6.3
        ''',
    ],
    [
        'none',
        'minimum-versions',
    ],
)
def test(session: nox.Session, constraints: str):
    "Run the test suite."
    _mirror_project(session)

    constraints_txt = 'constraints.txt'
    with open(constraints_txt, 'w') as file:
        file.write(dedent(constraints))

    session.install('-c', constraints_txt, '.[gui, test]', './tests/plugin')
    session.run('coverage', 'run', '-m', 'pytest')
    session.run('coverage', 'report', '-m')


@nox.session(python=SUPPORTED_PYTHON_VERSIONS)
def type_check(session: nox.Session):
    "Run Pyright."
    _mirror_project(session)
    session.install(
        '--use-feature=in-tree-build',
        '.[gui]',
        'sqlalchemy-stubs@ https://github.com/layday/sqlalchemy-stubs/archive/develop.zip',
    )
    session.run('npx', 'pyright', external=True)


@nox.session(python=False)
def bundle_frontend(session: nox.Session):
    "Bundle the frontend."
    for file in Path().glob('gui-webview/src/instawow_gui/frontend/svelte-*'):
        file.unlink()

    session.chdir('gui-webview/frontend')
    session.run('npx', 'rollup', '-c', external=True)


@nox.session
def build_dists(session: nox.Session):
    "Build an sdist and wheel."
    rmtree('dist', ignore_errors=True)
    session.install('build')
    session.run('python', '-m', 'build')


@nox.session
def publish_dists(session: nox.Session):
    "Build, validate and upload dists to PyPI."
    session.install('twine')
    for subcmd in ('check', 'upload'):
        session.run('twine', subcmd, 'dist/*')
