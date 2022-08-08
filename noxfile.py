from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import nox

nox.options.sessions = ['format', 'test', 'type_check']


def mirror_repo(session: nox.Session):
    repo_dir = f'{session.create_tmp()}/instawow'
    session.run('git', 'clone', '.', repo_dir, external=True)
    session.chdir(repo_dir)


def install_coverage_hook(session: nox.Session):
    session.run(
        'python',
        '-c',
        '''\
from pathlib import Path
import sysconfig

(Path(sysconfig.get_path('purelib')) / 'coverage.pth').write_text(
    'import coverage; coverage.process_startup()',
    encoding='utf-8',
)
''',
    )


@nox.session(name='format', reuse_venv=True)
def format_(session: nox.Session):
    "Format source code."
    session.install('isort', 'black')

    check = '--check' in session.posargs
    for cmd in ['isort', 'black']:
        session.run(
            cmd, *['--check'] if check else [], 'src', 'gui-webview/src', 'tests', 'noxfile.py'
        )

    if '--skip-prettier' not in session.posargs:
        session.chdir('gui-webview/frontend')
        session.run(
            'npx',
            'prettier',
            '--check' if check else '--write',
            'src',
            'package.json',
            'rollup.config.js',
            'tsconfig.json',
            external=True,
        )


@nox.session(python='3.9')
@nox.parametrize(
    'constraints',
    [
        '',
        dedent(
            '''\
            aiohttp == 3.7.4
            alembic == 1.7.0
            attrs == 21.4.0
            cattrs == 22.1.0
            click == 8.0.0
            exceptiongroup == 1.0.0rc5
            iso8601 == 1.0.2
            jinja2 == 3.0.0
            loguru == 0.5.3
            pluggy == 0.13.0
            prompt-toolkit == 3.0.29
            questionary == 1.10.0
            rapidfuzz == 1.4.1
            sqlalchemy == 1.4.23
            typing-extensions == 4.3.0
            yarl == 1.6.3
            aiohttp-rpc == 1.0.0
            '''
        ),
    ],
    [
        'latest',
        'minimum-versions',
    ],
)
def test(session: nox.Session, constraints: str):
    "Run the test suite."
    mirror_repo(session)

    constraints_txt = 'constraints.txt'
    Path(constraints_txt).write_text(constraints)

    session.install('-c', constraints_txt, '.[gui, test]', './tests/plugin')
    install_coverage_hook(session)

    session.run(
        *'coverage run -m pytest -n auto'.split(),
        env={'COVERAGE_PROCESS_START': 'pyproject.toml'},
    )
    session.run('coverage', 'combine')
    session.run('coverage', 'report', '-m')
    session.run('coverage', 'xml')


@nox.session(python='3.9')
def type_check(session: nox.Session):
    "Run Pyright."
    mirror_repo(session)
    session.install('.[gui, types]')
    session.run('npx', 'pyright', external=True)


@nox.session(python=False)
def bundle_frontend(session: nox.Session):
    "Bundle the frontend."
    session.run('git', 'clean', '-fX', 'gui-webview/src/instawow_gui/frontend', external=True)
    session.chdir('gui-webview/frontend')
    session.run('npm', 'install', external=True)
    session.run('npx', 'rollup', '-c', external=True)


@nox.session
def build_dists(session: nox.Session):
    "Build an sdist and wheel."
    session.run('git', 'clean', '-fdX', 'dist', external=True)
    session.install(
        'build',
        'poetry-core @ git+https://github.com/python-poetry/poetry-core@af08f1c',
        'poetry-dynamic-versioning',
    )
    session.run('python', '-m', 'build', '-n')


@nox.session
def publish_dists(session: nox.Session):
    "Validate and upload dists to PyPI."
    session.install('twine')
    session.run('twine', '--verbose', 'check', '--strict', 'dist/*')
    session.run('twine', '--verbose', 'upload', 'dist/*')


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
    session.run('git', 'clean', '-fX', 'instawow-standalone.spec', external=True)
