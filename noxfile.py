from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

import nox

nox.options.envdir = os.environ.get('NOX_ENVDIR')
nox.options.sessions = ['format', 'lint', 'test', 'type_check']


LINT_PATHS = [
    'src',
    'gui-webview/src',
    'tests',
    'types',
    'noxfile.py',
]


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
    session.install('-U', 'black', 'ruff')

    check = '--check' in session.posargs
    session.run('ruff', '--select', 'I', '--select', 'Q', *[] if check else ['--fix'], *LINT_PATHS)
    session.run('black', *['--check'] if check else [], *LINT_PATHS)

    if '--skip-prettier' not in session.posargs:
        paths = [
            'package.json',
            'rollup.config.mjs',
            'src',
            'tsconfig.json',
        ]
        session.chdir('gui-webview/frontend')
        session.run(
            'npx',
            'prettier',
            '--check' if check else '--write',
            *paths,
            external=True,
        )


@nox.session(reuse_venv=True)
def lint(session: nox.Session):
    "Lint source code."
    session.install('-U', 'ruff')
    session.run('ruff', '--format', 'grouped', '--show-source', *session.posargs, *LINT_PATHS)
    session.notify('format', ['--check'])


@nox.session(python='3.11')
@nox.parametrize(
    'constraints',
    [
        '',
        dedent(
            '''\
            aiohttp == 3.8.2
            aiohttp-client-cache == 0.8.0
            alembic == 1.9.0
            anyio == 3.6.2
            attrs == 23.1.0
            cattrs == 23.1.2
            click == 8.1.0
            iso8601 == 1.0.2
            loguru == 0.7.0
            mako == 1.2.4
            packaging == 23.0
            pluggy == 0.13.0
            prompt-toolkit == 3.0.29
            questionary == 1.10.0
            rapidfuzz == 2.12.0
            sqlalchemy == 2.0.0
            typing-extensions == 4.3.0
            yarl == 1.8.1
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

    if session.posargs:
        (package_path,) = session.posargs
    else:
        package_path = '.'

    session.install('-c', constraints_txt, f'{package_path}[gui, test]', './tests/plugin')
    install_coverage_hook(session)

    session.run(
        *'coverage run -m pytest -n auto'.split(),
        env={'COVERAGE_PROCESS_START': 'pyproject.toml'},
    )
    session.run('coverage', 'combine')
    session.run('coverage', 'report', '-m')
    session.run('coverage', 'xml')


@nox.session(python='3.11')
def type_check(session: nox.Session):
    "Run Pyright."
    mirror_repo(session)

    if session.posargs:
        (package_path,) = session.posargs
    else:
        package_path = '.'

    session.install(f'{package_path}[gui, types]')
    session.run('npx', 'pyright', external=True)


@nox.session(python=False)
def bundle_frontend(session: nox.Session):
    "Bundle the frontend."
    session.run('git', 'clean', '-fX', 'gui-webview/src/instawow_gui/frontend', external=True)
    session.chdir('gui-webview/frontend')
    session.run('npm', 'install', external=True)
    session.run('npx', 'svelte-check', external=True)
    session.run('npx', 'rollup', '-c', external=True)


@nox.session(python='3.11')
def build_dists(session: nox.Session):
    "Build an sdist and wheel."
    session.run('git', 'clean', '-fdX', 'dist', external=True)
    session.install('build')
    session.run('python', '-m', 'build')


@nox.session
def publish_dists(session: nox.Session):
    "Validate and upload dists to PyPI."
    session.install('twine')
    session.run('twine', 'check', '--strict', 'dist/*')
    session.run('twine', 'upload', '--verbose', 'dist/*')


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


@nox.session(python=False)
def extract_version(session: nox.Session):
    from importlib.metadata import Distribution

    (instawow,) = Distribution.discover(name='instawow', path=list(session.posargs))
    print(instawow.version, end='')


@nox.session(python=False)
def patch_frontend_spec(session: nox.Session):
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--version')
    parser.add_argument('--wheel-file')

    options = parser.parse_args(session.posargs)

    spec_path = Path(__file__).parent.joinpath('gui-webview', 'pyproject.toml')
    spec = spec_path.read_text(encoding='utf-8')

    if options.version:
        spec = spec.replace('version = "0.1.0"', f'version = "{options.version}"')

    if options.wheel_file:
        spec = spec.replace(
            '"..[gui]"', f'"instawow[gui] @ {Path(options.wheel_file).resolve().as_uri()}"'
        )

    spec_path.write_text(spec, encoding='utf-8')
