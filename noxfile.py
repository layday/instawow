from __future__ import annotations

from pathlib import Path
from shutil import rmtree
from textwrap import dedent

import nox

nox.options.sessions = ['reformat', 'test', 'type_check']


def _mirror_project(session: nox.Session):
    tmp_dir = session.create_tmp()
    session.run('git', 'clone', '.', tmp_dir, external=True)
    session.chdir(tmp_dir)


def _install_coverage_hook(session: nox.Session):
    session.run('python', 'tests/install_coverage_hook.py')


@nox.session(reuse_venv=True)
def reformat(session: nox.Session):
    "Reformat Python source code using Black and JavaScript using Prettier."
    session.install('isort', 'black')
    for cmd in ['isort', 'black']:
        session.run(cmd, 'src', 'gui-webview/src', 'tests', 'noxfile.py')

    if '--skip-prettier' not in session.posargs:
        session.chdir('gui-webview/frontend')
        session.run(
            *('npx', 'prettier', '-w', 'src', 'package.json', 'rollup.config.js', 'tsconfig.json'),
            external=True,
        )


@nox.session(python='3.9')
@nox.parametrize(
    'constraints',
    [
        '',
        dedent(
            '''\
            aiohttp ==3.7.4
            alembic ==1.7.0
            click ==7.1
            jinja2 ==2.11.0
            loguru ==0.5.0
            pluggy ==0.13.0
            prompt-toolkit ==3.0.15
            pydantic ==1.8.2
            questionary ==1.10.0
            rapidfuzz ==1.4.1
            sqlalchemy ==1.4.23
            typing-extensions ==3.10.0.0
            yarl ==1.6.3
            aiohttp-rpc ==1.0.0
            '''
        ),
    ],
    [
        'none',
        'minimum-versions',
    ],
)
def test(session: nox.Session, constraints: str):
    "Run the test suite."
    _mirror_project(session)
    _install_coverage_hook(session)

    constraints_txt = 'constraints.txt'
    with open(constraints_txt, 'w') as file:
        file.write(constraints)

    session.install('-c', constraints_txt, '.[gui, test]', './tests/plugin')
    session.run(
        *('coverage', 'run', '-m', 'pytest', '-n', 'auto'),
        env={'COVERAGE_PROCESS_START': 'pyproject.toml'},
    )
    session.run('coverage', 'combine')
    session.run('coverage', 'report', '-m')


@nox.session(python='3.9')
def type_check(session: nox.Session):
    "Run Pyright."
    _mirror_project(session)
    session.install('.[gui, types]')
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
    session.install(
        'build',
        'poetry-core @ git+https://github.com/layday/poetry-core@fix-multi-package-srcs',
        'poetry-dynamic-versioning',
    )
    session.run('python', '-m', 'build', '-n')


@nox.session
def publish_dists(session: nox.Session):
    "Build, validate and upload dists to PyPI."
    session.install('twine')
    for subcmd in ['check', 'upload']:
        session.run('twine', subcmd, 'dist/*')


@nox.session
def freeze_cli(session: nox.Session):
    session.install(
        'pyinstaller',
        '.',
        'certifi',
    )
    main_py = session.run(
        'python',
        '-c',
        'import instawow.__main__; print(instawow.__main__.__file__, end="")',
        silent=True,
    )
    assert main_py
    session.run(
        'pyinstaller',
        '--clean',
        '-y',
        '--onedir',
        '-n',
        'instawow-standalone',
        '--collect-all',
        'instawow',
        '--exclude-module',
        'instawow_gui',
        '--console',
        main_py,
    )
    Path('instawow-standalone.spec').unlink()
